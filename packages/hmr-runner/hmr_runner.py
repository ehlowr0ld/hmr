import inspect
from collections.abc import Awaitable, Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, override


@dataclass(frozen=True, slots=True)
class ReloadInfo:
    files: frozenset[Path]
    reasons: frozenset[str]


RELOAD_REASON_CODE = "code"
RELOAD_REASON_TRACKED_FILE = "tracked-file"
RELOAD_REASON_EXTRA_WATCH_FILE = "extra-watch-file"
RELOAD_REASON_ASSET_REFRESH = "asset-refresh"


@dataclass(frozen=True, slots=True)
class HMRConfig:
    reload_include: list[str] = field(default_factory=lambda: [str(Path.cwd())])
    reload_exclude: list[str] = field(default_factory=lambda: [".venv"])
    clear: bool = False
    refresh: bool = False
    extra_watch_files: list[Path] = field(default_factory=list)
    log_reload_events: bool = True

    # Passed through to watchfiles.{watch,awatch} when set. Use these to tune batching when your app restarts are slow.
    watch_debounce_ms: int | None = None
    watch_step_ms: int | None = None
    restart_cooldown_ms: int | None = None

    # Asset refresh-only watching (active only when `refresh` is True and a refresh callback is provided).
    asset_refresh_include: list[str] = field(default_factory=list)
    asset_refresh_exclude: list[str] = field(default_factory=list)


type HookReturn = None | Awaitable[None]
type ChangeDetectedHook = Callable[[ReloadInfo], HookReturn]
type ServerHook = Callable[[Any], HookReturn]
type ServerReloadHook = Callable[[Any, ReloadInfo], HookReturn]
type ReloadHook = Callable[[ReloadInfo], HookReturn]
type ReloadedHook = Callable[[Any, ReloadInfo], HookReturn]


@dataclass(frozen=True, slots=True)
class HMRHooks:
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


def _display_path(path: str | Path) -> str:
    p = Path(path).resolve()
    try:
        return f"'{p.relative_to(Path.cwd())}'"
    except ValueError:
        return f"'{p}'"


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


_GLOB_CHARS = frozenset({"*", "?", "["})


def _is_glob(s: str) -> bool:
    return any(c in s for c in _GLOB_CHARS)


@dataclass(frozen=True, slots=True)
class _Glob:
    pattern: str
    absolute: bool


@dataclass(frozen=True, slots=True)
class _CompiledAssetSpec:
    cwd: Path
    include_dir_roots: tuple[Path, ...]
    include_files: frozenset[Path]
    include_globs: tuple[_Glob, ...]
    exclude_dir_roots: tuple[Path, ...]
    exclude_files: frozenset[Path]
    exclude_globs: tuple[_Glob, ...]
    watch_paths: tuple[Path, ...]

    def matches(self, path: Path) -> bool:
        if path.suffix == ".py":
            return False

        if not self._matches_any_include(path):
            return False

        return not self._matches_any_exclude(path)

    def _matches_any_include(self, path: Path) -> bool:
        if self.include_files and path in self.include_files:
            return True
        if self.include_dir_roots and any(path.is_relative_to(root) for root in self.include_dir_roots):
            return True
        return self._matches_any_glob(path, self.include_globs)

    def _matches_any_exclude(self, path: Path) -> bool:
        if self.exclude_files and path in self.exclude_files:
            return True
        if self.exclude_dir_roots and any(path.is_relative_to(root) for root in self.exclude_dir_roots):
            return True
        return self._matches_any_glob(path, self.exclude_globs)

    def _matches_any_glob(self, path: Path, globs: tuple[_Glob, ...]) -> bool:
        if not globs:
            return False

        abs_posix = path.as_posix()
        rel_posix: str | None
        try:
            rel_posix = path.relative_to(self.cwd).as_posix()
        except ValueError:
            rel_posix = None

        for g in globs:
            candidate = abs_posix if g.absolute else rel_posix
            if candidate is not None and fnmatch(candidate, g.pattern):
                return True
        return False


def _nearest_existing_dir(path: Path) -> Path | None:
    cur = path
    while True:
        if cur.is_dir():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


def _glob_base_dir(pattern: str) -> Path:
    idx = min((pattern.find(c) for c in _GLOB_CHARS if c in pattern), default=-1)
    if idx <= 0:
        return Path.cwd()

    prefix = pattern[:idx]
    base = Path(prefix)
    if prefix and not prefix.endswith(("/", "\\")):
        base = base.parent
    return base


def _compile_asset_spec(*, include: list[str], exclude: list[str], cwd: Path, logger) -> _CompiledAssetSpec | None:
    if not include:
        return None

    include_dir_roots: list[Path] = []
    include_files: set[Path] = set()
    include_globs: list[_Glob] = []

    exclude_dir_roots: list[Path] = []
    exclude_files: set[Path] = set()
    exclude_globs: list[_Glob] = []

    watch_paths: list[Path] = []

    def add_path_spec(spec: str, *, to_dirs: list[Path], to_files: set[Path], watch: bool) -> None:
        raw = spec
        p = Path(spec).expanduser()
        if not p.is_absolute():
            p = cwd / p
        p = p.resolve()

        is_dir_hint = raw.endswith(("/", "\\")) or Path(raw).suffix == ""
        if p.exists():
            if p.is_dir():
                to_dirs.append(p)
                if watch:
                    watch_paths.append(p)
                return
            to_files.add(p)
            if watch:
                watch_paths.append(p)
            return

        if is_dir_hint:
            to_dirs.append(p)
            if watch:
                parent = _nearest_existing_dir(p)
                if parent is not None:
                    watch_paths.append(parent)
                else:
                    logger.warning("Asset refresh include path does not exist and has no existing parent: %s", _display_path(p))
            return

        to_files.add(p)
        if watch:
            parent = _nearest_existing_dir(p.parent)
            if parent is not None:
                watch_paths.append(parent)
            else:
                logger.warning("Asset refresh include file does not exist and has no existing parent: %s", _display_path(p))

    def add_glob_spec(spec: str, *, to_globs: list[_Glob], watch: bool) -> None:
        expanded = str(Path(spec).expanduser())
        absolute = Path(expanded).is_absolute()
        pattern = Path(expanded).as_posix() if absolute else expanded.replace("\\", "/")
        to_globs.append(_Glob(pattern=pattern, absolute=absolute))

        if watch:
            base_dir = _glob_base_dir(expanded)
            if not base_dir.is_absolute():
                base_dir = cwd / base_dir
            base_dir = base_dir.resolve()
            existing = _nearest_existing_dir(base_dir)
            if existing is not None:
                watch_paths.append(existing)
            else:
                logger.warning("Asset refresh glob has no existing base directory to watch: %s", spec)

    for spec in include:
        if _is_glob(spec):
            add_glob_spec(spec, to_globs=include_globs, watch=True)
        else:
            add_path_spec(spec, to_dirs=include_dir_roots, to_files=include_files, watch=True)

    for spec in exclude:
        if _is_glob(spec):
            add_glob_spec(spec, to_globs=exclude_globs, watch=False)
        else:
            add_path_spec(spec, to_dirs=exclude_dir_roots, to_files=exclude_files, watch=False)

    def uniq_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
        dedup: dict[Path, None] = {}
        for p in paths:
            dedup[p] = None
        return tuple(dedup.keys())

    return _CompiledAssetSpec(
        cwd=cwd,
        include_dir_roots=tuple(include_dir_roots),
        include_files=frozenset(include_files),
        include_globs=tuple(include_globs),
        exclude_dir_roots=tuple(exclude_dir_roots),
        exclude_files=frozenset(exclude_files),
        exclude_globs=tuple(exclude_globs),
        watch_paths=uniq_paths(watch_paths),
    )


async def run_with_hmr_async(
    *,
    entry: str | Path,
    load_app: Callable[[], Any],
    make_server: Callable[[Any], Any],
    hmr: HMRConfig | None = None,
    hooks: HMRHooks | None = None,
    logger_name: str = "uvicorn.error",
    server_ready_event=None,
    name: str = "app",
    refresh_callback: Callable[[], Any] | None = None,
    force_restart_files: set[Path] | None = None,
) -> None:
    from asyncio import CancelledError, Event, ensure_future, sleep
    from logging import getLogger
    from time import monotonic

    from reactivity.hmr.core import HMR_CONTEXT, AsyncReloader, ReactiveModule, is_relative_to_any
    from reactivity.hmr.fs import fs_signals, track
    from reactivity.hmr.hooks import call_post_reload_hooks, call_pre_reload_hooks

    logger = getLogger(logger_name)
    hmr = hmr or HMRConfig()
    hooks = hooks or HMRHooks()

    entry_path = Path(entry).resolve()
    entry_str = str(entry_path)
    cwd = Path.cwd().resolve()

    refresh_cb = refresh_callback if (hmr.refresh and refresh_callback is not None) else None
    refresh_enabled = refresh_cb is not None
    asset_spec = _compile_asset_spec(include=hmr.asset_refresh_include, exclude=hmr.asset_refresh_exclude, cwd=cwd, logger=logger) if refresh_enabled else None

    finish = Event()
    manage_ready_event = server_ready_event is None
    server_ready_event = server_ready_event or Event()

    extra_watch_files = [*{p.expanduser().resolve(): None for p in hmr.extra_watch_files if p.expanduser().exists()}]
    extra_watch_set = set(extra_watch_files)
    force_restart_set = {p.resolve() for p in (force_restart_files or set())}

    need_restart = True
    server: Any | None = None
    last_server_start: float | None = None

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
                    if all(is_relative_to_any(path, ignored_paths) or not is_relative_to_any(path, watched_paths) for path in ReactiveModule.instances):
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
            roots = [Path(p).resolve() for p in watch_paths]

            for p in extra_watch_files:
                if not any(p.is_relative_to(r) for r in roots if r.is_dir()):
                    watch_paths.append(str(p))

            if asset_spec is not None:
                for p in asset_spec.watch_paths:
                    if not any(p.is_relative_to(r) for r in roots if r.is_dir()):
                        watch_paths.append(str(p))

            awatch_kwargs: dict[str, Any] = {"stop_event": self._stop_event}
            if hmr.watch_debounce_ms is not None:
                awatch_kwargs["debounce"] = hmr.watch_debounce_ms
            if hmr.watch_step_ms is not None:
                awatch_kwargs["step"] = hmr.watch_step_ms

            async for events in awatch(*watch_paths, **awatch_kwargs):
                self.on_events(events)

            del self._stop_event

        def _schedule_task(self, coro_or_none: Any) -> None:
            if coro_or_none is None:
                return
            if inspect.isawaitable(coro_or_none):
                task = ensure_future(coro_or_none)
                self._hook_tasks.add(task)
                task.add_done_callback(self._hook_tasks.discard)

        @override
        def on_changes(self, files: set[Path]):
            tracked_hits = files.intersection(path for path, s in fs_signals.items() if s.subscribers)
            code_hits = files.intersection(ReactiveModule.instances)
            extra_hits = files.intersection(extra_watch_set) if extra_watch_set else set()

            asset_hits: set[Path] = set()
            if asset_spec is not None and refresh_cb is not None:
                asset_hits = {p for p in files if not p.is_dir() and asset_spec.matches(p)}

            if not (tracked_hits or code_hits or extra_hits or asset_hits):
                return None

            protected_extra_hits = extra_hits.intersection(force_restart_set) if force_restart_set else set()
            restart_tracked_hits = tracked_hits - asset_hits
            restart_extra_hits = (extra_hits - asset_hits) | protected_extra_hits

            if not (code_hits or restart_tracked_hits or restart_extra_hits) and asset_hits and refresh_cb is not None:
                # Refresh-only change: do not restart the server.
                if hmr.log_reload_events:
                    logger.warning("Assets changed (%d file(s)). Refreshing browser...", len(asset_hits))

                info = ReloadInfo(files=frozenset(asset_hits), reasons=frozenset({RELOAD_REASON_ASSET_REFRESH}))
                self._schedule_task(_call_hook(logger, "on_change_detected", hooks.on_change_detected, info))

                try:
                    res = refresh_cb()
                    self._schedule_task(res)
                except Exception:
                    logger.exception("Asset refresh callback failed")

                return None

            if hmr.clear:
                print("\033c", end="", flush=True)

            reasons: set[str] = set()
            if code_hits:
                reasons.add(RELOAD_REASON_CODE)
            if restart_tracked_hits:
                reasons.add(RELOAD_REASON_TRACKED_FILE)
            if restart_extra_hits:
                reasons.add(RELOAD_REASON_EXTRA_WATCH_FILE)
            if asset_hits:
                reasons.add(RELOAD_REASON_ASSET_REFRESH)

            relevant_files = set(code_hits) | set(restart_tracked_hits) | set(restart_extra_hits) | set(asset_hits)
            info = ReloadInfo(files=frozenset(relevant_files), reasons=frozenset(reasons))
            self._merge_reload_info(info)
            self._schedule_task(_call_hook(logger, "on_change_detected", hooks.on_change_detected, info))

            if hmr.log_reload_events:
                logger.warning("Watchfiles detected changes in %s. Reloading...", ", ".join(map(_display_path, relevant_files)))

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

                        if hmr.restart_cooldown_ms is not None and last_server_start is not None:
                            now = monotonic()
                            next_allowed = last_server_start + (hmr.restart_cooldown_ms / 1000)
                            if now < next_allowed:
                                await sleep(next_allowed - now)

                        srv = make_server(reloader.app)
                        if inspect.isawaitable(srv):
                            srv = await srv
                        server = srv
                        await _call_hook(logger, "on_server_created", hooks.on_server_created, srv)
                        try:
                            if manage_ready_event:
                                server_ready_event.set()
                            last_server_start = monotonic()
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
    hmr: HMRConfig | None = None,
    hooks: HMRHooks | None = None,
    logger_name: str = "uvicorn.error",
    server_ready_event=None,
    name: str = "app",
    refresh_callback: Callable[[], Any] | None = None,
    force_restart_files: set[Path] | None = None,
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
            refresh_callback=refresh_callback,
            force_restart_files=force_restart_files,
        )
    )
