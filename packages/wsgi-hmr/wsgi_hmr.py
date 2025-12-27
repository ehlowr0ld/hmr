import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from hmr_reloader import send_reload_signal, wsgi_auto_refresh_middleware
from hmr_runner import HMRConfig, HMRHooks, ReloadInfo, run_with_hmr, run_with_hmr_async
from typer import Argument, Option, Typer, secho

WSGIHMRConfig = HMRConfig
WSGIHMRHooks = HMRHooks

__all__ = [
    "ReloadInfo",
    "WSGIHMRConfig",
    "WSGIHMRHooks",
    "app",
    "main",
    "run_slug_with_hmr",
    "run_with_hmr",
    "run_with_hmr_async",
]


@dataclass(frozen=True, slots=True)
class ResolvedSlug:
    slug: str
    module: str
    attr: str
    file: Path


def _resolve_slug(slug: str) -> ResolvedSlug:
    if ":" not in slug:
        raise ValueError(f"Invalid slug (expected 'module:attr'): {slug!r}")

    module, attr = slug.split(":", 1)
    fragment = module.replace(".", "/")

    for path in ("", *sys.path):
        if (file := Path(path, f"{fragment}.py")).is_file():
            break
        if (file := Path(path, fragment, "__init__.py")).is_file():
            break
    else:
        raise ModuleNotFoundError(f"Module {module!r} not found on sys.path")

    return ResolvedSlug(slug=slug, module=module, attr=attr, file=file.resolve())


def _make_server_factory(*, host: str, port: int, refresh: bool) -> Callable[[Any], Any]:
    from werkzeug.serving import make_server

    class _Server:
        def __init__(self, app: Any):
            self._server = make_server(host=host, port=port, app=app, threaded=True)
            self._should_exit = False

        @property
        def should_exit(self) -> bool:
            return self._should_exit

        @should_exit.setter
        def should_exit(self, value: bool) -> None:
            v = bool(value)
            if v and not self._should_exit:
                self._should_exit = True
                if refresh:
                    send_reload_signal()
                self._server.shutdown()

        async def serve(self) -> None:
            from asyncio import to_thread

            try:
                await to_thread(self._server.serve_forever)
            finally:
                self._server.server_close()

    def make(app: Any) -> _Server:
        return _Server(app)

    return make


def run_slug_with_hmr(
    slug: str,
    *,
    reload_include: list[str] | None = None,
    reload_exclude: list[str] | None = None,
    asset_include: list[str] | None = None,
    asset_exclude: list[str] | None = None,
    watch_debounce_ms: int | None = None,
    watch_step_ms: int | None = None,
    restart_cooldown_ms: int | None = None,
    host: str = "localhost",
    port: int = 8000,
    refresh: bool = False,
    clear: bool = False,
    hooks: WSGIHMRHooks | None = None,
    logger_name: str = "werkzeug",
) -> None:
    resolved = _resolve_slug(slug)
    if resolved.module in sys.modules:
        raise RuntimeError(f"It seems you've already imported `{resolved.module}` as a normal module. You should call `reactivity.hmr.core.patch_meta_path()` before it.")

    from importlib import import_module

    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    def load_app():
        app = getattr(import_module(resolved.module), resolved.attr)
        if refresh:
            app = wsgi_auto_refresh_middleware(app)
        return app

    make_server = _make_server_factory(host=host, port=port, refresh=refresh)

    hmr = WSGIHMRConfig(
        reload_include=reload_include or [str(Path.cwd())],
        reload_exclude=reload_exclude or [".venv"],
        clear=clear,
        refresh=refresh,
        asset_refresh_include=asset_include or [],
        asset_refresh_exclude=asset_exclude or [],
        watch_debounce_ms=watch_debounce_ms,
        watch_step_ms=watch_step_ms,
        restart_cooldown_ms=restart_cooldown_ms,
    )

    run_with_hmr(
        entry=resolved.file,
        load_app=load_app,
        make_server=make_server,
        hmr=hmr,
        hooks=hooks,
        logger_name=logger_name,
        name=slug,
        refresh_callback=send_reload_signal if refresh else None,
    )


app = Typer(help="Hot Module Replacement for WSGI development servers (Werkzeug)", add_completion=False, pretty_exceptions_enable=False, rich_markup_mode="markdown")


@app.command(no_args_is_help=True)
def main(
    slug: Annotated[str, Argument()] = "main:app",
    reload_include: list[str] = [str(Path.cwd())],  # noqa: B006, B008
    reload_exclude: list[str] = [".venv"],  # noqa: B006
    asset_include: Annotated[list[str], Option("--asset-include", help="Asset refresh include (paths or globs). Requires --refresh.")] = [],  # noqa: B006
    asset_exclude: Annotated[list[str], Option("--asset-exclude", help="Asset refresh exclude (paths or globs). Requires --refresh.")] = [],  # noqa: B006
    watch_debounce_ms: Annotated[int | None, Option("--watch-debounce-ms", min=0, help="Override watchfiles debounce in milliseconds (batching window).")] = None,
    watch_step_ms: Annotated[int | None, Option("--watch-step-ms", min=1, help="Override watchfiles step in milliseconds (polling granularity).")] = None,
    restart_cooldown_ms: Annotated[int | None, Option("--restart-cooldown-ms", min=0, help="Minimum interval between server starts (rate-limit restarts).")] = None,
    host: str = "localhost",
    port: int = 8000,
    refresh: Annotated[bool, Option("--refresh", help="Enable automatic browser page refreshing (WSGI injection + /---fastapi-reloader--- endpoint).")] = False,  # noqa: FBT002
    clear: Annotated[bool, Option("--clear", help="Clear the terminal before restarting the server")] = False,  # noqa: FBT002
):
    if ":" not in slug:
        secho("Invalid slug: ", fg="red", nl=False)
        secho(slug, fg="yellow")
        exit(1)
    try:
        run_slug_with_hmr(
            slug,
            reload_include=reload_include,
            reload_exclude=reload_exclude,
            asset_include=asset_include,
            asset_exclude=asset_exclude,
            watch_debounce_ms=watch_debounce_ms,
            watch_step_ms=watch_step_ms,
            restart_cooldown_ms=restart_cooldown_ms,
            host=host,
            port=port,
            refresh=refresh,
            clear=clear,
        )
    except ModuleNotFoundError:
        module = slug.split(":", 1)[0]
        secho("Module", fg="red", nl=False)
        secho(f" {module} ", fg="yellow", nl=False)
        secho("not found.", fg="red")
        exit(1)
    except RuntimeError as e:
        return secho(str(e), fg="red")


if __name__ == "__main__":
    app()
