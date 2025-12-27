import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Annotated

from hmr_runner import HMRConfig, HMRHooks, ReloadInfo, run_with_hmr, run_with_hmr_async
from typer import Argument, Option, Typer, secho

UvicornHMRConfig = HMRConfig
UvicornHMRHooks = HMRHooks

__all__ = [
    "ReloadInfo",
    "UvicornHMRConfig",
    "UvicornHMRHooks",
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


def _lazy_import_from_uvicorn(*, refresh: bool, main_loop_started, until, hmr_context, state_fn):
    from asyncio import FIRST_COMPLETED, ensure_future, sleep, wait
    from signal import SIGINT

    from uvicorn import Config, Server

    class _Server(Server):
        should_exit = state_fn(False, context=hmr_context)  # noqa: FBT003

        def handle_exit(self, sig, frame):
            if self.force_exit and sig == SIGINT:
                raise KeyboardInterrupt  # allow immediate shutdown on third interrupt
            return super().handle_exit(sig, frame)

        async def main_loop(self):
            main_loop_started.set()
            if await self.on_tick(0):
                return

            async def ticking():
                counter = 10
                while not self.should_exit:
                    await sleep(1 - time() % 1)
                    self.should_exit |= await self.on_tick(counter)
                    counter += 10

            await wait((until(lambda: self.should_exit), ensure_future(ticking())), return_when=FIRST_COMPLETED)

        if refresh:

            def shutdown(self, sockets=None):
                _try_refresh()
                return super().shutdown(sockets)

            def _wait_tasks_to_complete(self):
                _try_refresh()
                return super()._wait_tasks_to_complete()

    return _Server, Config


def _make_default_server_factory(*, host: str, port: int, env_file: Path | None, log_level: str | None, refresh: bool, main_loop_started, until, hmr_context, state_fn):
    server_cls, config_cls = _lazy_import_from_uvicorn(
        refresh=refresh,
        main_loop_started=main_loop_started,
        until=until,
        hmr_context=hmr_context,
        state_fn=state_fn,
    )

    def make_server(app):
        return server_cls(config_cls(app, host, port, env_file=env_file, log_level=log_level))

    return make_server


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
    env_file: Path | None = None,
    log_level: str | None = "info",
    refresh: bool = False,
    clear: bool = False,
    hooks: UvicornHMRHooks | None = None,
    logger_name: str = "uvicorn.error",
) -> None:
    resolved = _resolve_slug(slug)
    if resolved.module in sys.modules:
        raise RuntimeError(f"It seems you've already imported `{resolved.module}` as a normal module. You should call `reactivity.hmr.core.patch_meta_path()` before it.")

    from asyncio import Event, Future
    from importlib import import_module

    from reactivity import state
    from reactivity.hmr.core import HMR_CONTEXT

    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    def load_app():
        app = getattr(import_module(resolved.module), resolved.attr)
        if refresh:
            app = _try_patch(app)
        return app

    server_ready = Event()

    def until(func: Callable[[], bool]):
        future = Future()
        future.add_done_callback(lambda _: check.dispose())

        @HMR_CONTEXT.effect
        def check():
            if func():
                future.set_result(None)

        return future

    make_server = _make_default_server_factory(
        host=host,
        port=port,
        env_file=env_file,
        log_level=log_level,
        refresh=refresh,
        main_loop_started=server_ready,
        until=until,
        hmr_context=HMR_CONTEXT,
        state_fn=state,
    )

    extra_watch_files: list[Path] = []
    force_restart_files: set[Path] | None = None
    if env_file is not None and env_file.expanduser().is_file():
        env_path = env_file.expanduser().resolve()
        extra_watch_files.append(env_path)
        force_restart_files = {env_path}

    hmr = UvicornHMRConfig(
        reload_include=reload_include or [str(Path.cwd())],
        reload_exclude=reload_exclude or [".venv"],
        clear=clear,
        refresh=refresh,
        extra_watch_files=extra_watch_files,
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
        server_ready_event=server_ready,
        name=slug,
        refresh_callback=_try_refresh if refresh else None,
        force_restart_files=force_restart_files,
    )


app = Typer(help="Hot Module Replacement for Uvicorn", add_completion=False, pretty_exceptions_enable=False, rich_markup_mode="markdown")


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
    env_file: Path | None = None,
    log_level: str | None = "info",
    refresh: Annotated[bool, Option("--refresh", help="Enable automatic browser page refreshing with `fastapi-reloader` (requires installation)")] = False,  # noqa: FBT002
    clear: Annotated[bool, Option("--clear", help="Clear the terminal before restarting the server")] = False,  # noqa: FBT002
    reload: Annotated[bool, Option("--reload", hidden=True)] = False,  # noqa: FBT002
):
    if reload:
        secho("\nWarning: The `--reload` flag is deprecated in favor of `--refresh` to avoid ambiguity.\n", fg="yellow")
        refresh = reload  # For backward compatibility, map reload to refresh
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
            env_file=env_file,
            log_level=log_level,
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


def _display_path(path: str | Path):
    p = Path(path).resolve()
    try:
        return f"'{p.relative_to(Path.cwd())}'"
    except ValueError:
        return f"'{p}'"


NOTE = """
When you enable the `--refresh` flag, it means you want to use the `fastapi-reloader` package to enable automatic HTML page refreshing.
This behavior differs from Uvicorn's built-in `--reload` functionality.

Server reloading is a core feature of `uvicorn-hmr` and is always active, regardless of whether the `--refresh` flag is set.
The `--refresh` flag specifically controls auto-refreshing of HTML pages, a feature not available in Uvicorn.

If you don't need HTML page auto-refreshing, simply omit the `--refresh` flag.
If you do want this feature, ensure that `fastapi-reloader` is installed by running: `pip install fastapi-reloader` or `pip install uvicorn-hmr[all]`.
"""


def _try_patch(app):
    try:
        from fastapi_reloader import patch_for_auto_reloading

        return patch_for_auto_reloading(app)

    except ImportError:
        secho(NOTE, fg="red")
        raise


def _try_refresh():
    try:
        from fastapi_reloader import send_reload_signal

        send_reload_signal()
    except ImportError:
        secho(NOTE, fg="red")
        raise


if __name__ == "__main__":
    app()
