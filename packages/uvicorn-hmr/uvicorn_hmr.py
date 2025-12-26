import inspect
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Annotated, Any, override

from typer import Argument, Option, Typer, secho


@dataclass(frozen=True, slots=True)
class ReloadInfo:
    files: frozenset[Path]
    reasons: frozenset[str]


RELOAD_REASON_CODE = "code"
RELOAD_REASON_TRACKED_FILE = "tracked-file"
RELOAD_REASON_EXTRA_WATCH_FILE = "extra-watch-file"


@dataclass(frozen=True, slots=True)
class UvicornHMRConfig:
    reload_include: list[str] = field(default_factory=lambda: [str(Path.cwd())])
    reload_exclude: list[str] = field(default_factory=lambda: [".venv"])
    clear: bool = False
    refresh: bool = False
    extra_watch_files: list[Path] = field(default_factory=list)
    log_reload_events: bool = True


type HookReturn = None | Awaitable[None]
type ChangeDetectedHook = Callable[[ReloadInfo], HookReturn]
type ServerHook = Callable[[Any], HookReturn]
type ServerReloadHook = Callable[[Any, ReloadInfo], HookReturn]
type ReloadHook = Callable[[ReloadInfo], HookReturn]
type ReloadedHook = Callable[[Any, ReloadInfo], HookReturn]


@dataclass(frozen=True, slots=True)
class UvicornHMRHooks:
    """Optional lifecycle hooks for programmatic embedding.

    Hook order during a reload cycle:
    - on_change_detected(info) [when watchfiles reports relevant changes]
    - before_shutdown(server, info) [when a server is running and shutdown is requested]
    - after_shutdown(server, info) [after the previous server has stopped]
    - before_reload(info) [just before loading the app for the next generation]
    - after_reload(app, info) [after loading the new app]
    - on_server_created(server) [after creating the next server instance]
    - on_server_stopped(server) [after serve() returns for a generation]
    """

    on_change_detected: ChangeDetectedHook | None = None
    before_shutdown: ServerReloadHook | None = None
    after_shutdown: ServerReloadHook | None = None
    before_reload: ReloadHook | None = None
    after_reload: ReloadedHook | None = None
    on_server_created: ServerHook | None = None
    on_server_stopped: ServerHook | None = None


async def _call_hook(logger, hook_name: str, hook: Callable[..., HookReturn] | None, *args: Any) -> None:
    if hook is None:
        return
    try:
        res = hook(*args)
        if inspect.isawaitable(res):
            await res
    except Exception:
        logger.exception("Hook '%s' failed", hook_name)


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


@contextmanager
def _patch_reactive_module_load_logging(*, logger):
    from functools import wraps

    from reactivity.hmr.core import ReactiveModule
    from reactivity.hmr.utils import on_dispose

    __load = ReactiveModule.__load if TYPE_CHECKING else ReactiveModule._ReactiveModule__load  # noqa: SLF001

    @wraps(original_load := __load.method)
    def patched_load(self: ReactiveModule, *args: Any, **kwargs: Any):
        try:
            original_load(self, *args, **kwargs)
        finally:
            file: Path = self._ReactiveModule__file  # type: ignore[attr-defined]
            on_dispose(lambda: logger.info("Reloading module '%s' from %s", self.__name__, _display_path(file)), str(file))

    __load.method = patched_load
    try:
        yield
    finally:
        __load.method = original_load


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


async def run_with_hmr_async(
    *,
    entry: str | Path,
    load_app: Callable[[], Any],
    make_server: Callable[[Any], Any],
    hmr: UvicornHMRConfig | None = None,
    hooks: UvicornHMRHooks | None = None,
    logger_name: str = "uvicorn.error",
    server_ready_event=None,
    name: str = "app",
) -> None:
    from asyncio import CancelledError, Event, ensure_future
    from logging import getLogger

    from reactivity.hmr.core import HMR_CONTEXT, AsyncReloader, ReactiveModule, is_relative_to_any
    from reactivity.hmr.fs import fs_signals, track
    from reactivity.hmr.hooks import call_post_reload_hooks, call_pre_reload_hooks

    logger = getLogger(logger_name)
    hmr = hmr or UvicornHMRConfig()
    hooks = hooks or UvicornHMRHooks()

    entry_path = Path(entry).resolve()
    entry_str = str(entry_path)

    finish = Event()
    manage_ready_event = server_ready_event is None
    server_ready_event = server_ready_event or Event()

    extra_watch_files = [*{p.expanduser().resolve(): None for p in hmr.extra_watch_files if p.expanduser().exists()}]
    extra_watch_set = set(extra_watch_files)

    need_restart = True
    server: Any | None = None

    class Reloader(AsyncReloader):
        def __init__(self):
            super().__init__(entry_str, [entry_str, *hmr.reload_include], hmr.reload_exclude)
            self.error_filter.exclude_filenames.add(__file__)  # exclude error stacks within this file
            self.ready = Event()
            self._run = HMR_CONTEXT.async_derived(self.__run)
            self._pending_reload: ReloadInfo | None = None
            self._hook_tasks: set[Any] = set()

        def _merge_reload_info(self, info: ReloadInfo) -> None:
            if self._pending_reload is None:
                self._pending_reload = info
                return
            self._pending_reload = ReloadInfo(
                files=frozenset(set(self._pending_reload.files) | set(info.files)),
                reasons=frozenset(set(self._pending_reload.reasons) | set(info.reasons)),
            )

        def _drain_reload_info(self) -> ReloadInfo:
            info = self._pending_reload
            self._pending_reload = None
            return info or ReloadInfo(files=frozenset(), reasons=frozenset())

        async def __run(self):
            nonlocal server
            info = self._drain_reload_info()

            if server:
                if hmr.log_reload_events:
                    logger.warning("Application '%s' has changed. Restarting server...", name)
                self.ready.clear()
                await server_ready_event.wait()
                old_server = server
                await _call_hook(logger, "before_shutdown", hooks.before_shutdown, old_server, info)
                old_server.should_exit = True
                await finish.wait()
                await _call_hook(logger, "after_shutdown", hooks.after_shutdown, old_server, info)

            cancelled: CancelledError | None = None
            with self.error_filter:
                try:
                    for p in extra_watch_files:
                        track(p)

                    await _call_hook(logger, "before_reload", hooks.before_reload, info)

                    app = load_app()
                    if inspect.isawaitable(app):
                        app = await app
                    self.app = app

                    await _call_hook(logger, "after_reload", hooks.after_reload, self.app, info)

                    watched_paths = [Path(p).resolve() for p in self.includes]
                    ignored_paths = [Path(p).resolve() for p in self.excludes]
                    if all(
                        is_relative_to_any(path, ignored_paths) or not is_relative_to_any(path, watched_paths)
                        for path in ReactiveModule.instances
                    ):
                        logger.error("No files to watch for changes. The server will never reload.")
                except CancelledError as e:
                    cancelled = e

            if cancelled is not None:
                raise cancelled

            return self.app

        async def run(self):
            while True:
                await self._run()
                if not self._run.dirty:  # in case user code changed during reload
                    break
            self.ready.set()

        async def __aenter__(self):
            call_pre_reload_hooks()
            self.__run_effect = HMR_CONTEXT.async_effect(self.run, call_immediately=False)
            await self.__run_effect()
            call_post_reload_hooks()
            self.__reloader_task = ensure_future(self.start_watching())
            return self

        async def __aexit__(self, *_):
            self.stop_watching()
            self.__run_effect.dispose()
            await self.__reloader_task

        async def start_watching(self):
            await server_ready_event.wait()
            from watchfiles import awatch

            watch_paths: list[str] = [self.entry, *self.includes]
            if extra_watch_files:
                roots = [Path(p).resolve() for p in watch_paths]
                for p in extra_watch_files:
                    if not any(p.is_relative_to(r) for r in roots if r.is_dir()):
                        watch_paths.append(str(p))

            async for events in awatch(*watch_paths, stop_event=self._stop_event):
                self.on_events(events)

            del self._stop_event

        @override
        def on_changes(self, files: set[Path]):
            tracked_hits = files.intersection(path for path, s in fs_signals.items() if s.subscribers)
            code_hits = files.intersection(ReactiveModule.instances)
            extra_hits = files.intersection(extra_watch_set) if extra_watch_set else set()
            if not (tracked_hits or code_hits or extra_hits):
                return None

            if hmr.clear:
                print("\033c", end="", flush=True)

            reasons: set[str] = set()
            if code_hits:
                reasons.add(RELOAD_REASON_CODE)
            if tracked_hits:
                reasons.add(RELOAD_REASON_TRACKED_FILE)
            if extra_hits:
                reasons.add(RELOAD_REASON_EXTRA_WATCH_FILE)

            info = ReloadInfo(files=frozenset(files), reasons=frozenset(reasons))
            self._merge_reload_info(info)
            task = ensure_future(_call_hook(logger, "on_change_detected", hooks.on_change_detected, info))
            self._hook_tasks.add(task)
            task.add_done_callback(self._hook_tasks.discard)

            if hmr.log_reload_events:
                logger.warning("Watchfiles detected changes in %s. Reloading...", ", ".join(map(_display_path, files)))

            nonlocal need_restart
            need_restart = True
            return super().on_changes(files)

    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(_patch_reactive_module_load_logging(logger=logger))
        async with Reloader() as reloader:
            while need_restart:
                need_restart = False
                cancelled: CancelledError | None = None
                with reloader.error_filter:
                    try:
                        await reloader.ready.wait()
                        srv = make_server(reloader.app)
                        if inspect.isawaitable(srv):
                            srv = await srv
                        server = srv
                        await _call_hook(logger, "on_server_created", hooks.on_server_created, srv)
                        try:
                            if manage_ready_event:
                                server_ready_event.set()
                            await srv.serve()
                        except KeyboardInterrupt:
                            break
                        except CancelledError as e:
                            cancelled = e
                        finally:
                            finish.set()
                            finish.clear()
                            await _call_hook(logger, "on_server_stopped", hooks.on_server_stopped, srv)
                            server = None
                            server_ready_event.clear()
                    except CancelledError as e:
                        cancelled = e

                if cancelled is not None:
                    raise cancelled


def run_with_hmr(
    *,
    entry: str | Path,
    load_app: Callable[[], Any],
    make_server: Callable[[Any], Any],
    hmr: UvicornHMRConfig | None = None,
    hooks: UvicornHMRHooks | None = None,
    logger_name: str = "uvicorn.error",
    server_ready_event=None,
    name: str = "app",
) -> None:
    from asyncio import run

    run(
        run_with_hmr_async(
            entry=entry,
            load_app=load_app,
            make_server=make_server,
            hmr=hmr,
            hooks=hooks,
            logger_name=logger_name,
            server_ready_event=server_ready_event,
            name=name,
        )
    )


def run_slug_with_hmr(
    slug: str,
    *,
    reload_include: list[str] | None = None,
    reload_exclude: list[str] | None = None,
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
    if env_file is not None and env_file.expanduser().is_file():
        extra_watch_files.append(env_file.expanduser().resolve())

    hmr = UvicornHMRConfig(
        reload_include=reload_include or [str(Path.cwd())],
        reload_exclude=reload_exclude or [".venv"],
        clear=clear,
        refresh=refresh,
        extra_watch_files=extra_watch_files,
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
    )


app = Typer(help="Hot Module Replacement for Uvicorn", add_completion=False, pretty_exceptions_enable=False, rich_markup_mode="markdown")


@app.command(no_args_is_help=True)
def main(
    slug: Annotated[str, Argument()] = "main:app",
    reload_include: list[str] = [str(Path.cwd())],  # noqa: B006, B008
    reload_exclude: list[str] = [".venv"],  # noqa: B006
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
