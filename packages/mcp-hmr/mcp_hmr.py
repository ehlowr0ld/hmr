import hashlib
import logging
import os
import sys
from importlib import import_module
from importlib.machinery import ModuleSpec
from importlib.util import find_spec, module_from_spec
from pathlib import Path
from typing import Any

__version__ = "0.0.3.1"

__all__ = "mcp_server", "run_with_hmr"


def _is_valid_env_key(key: str) -> bool:
    if not key:
        return False
    first = key[0]
    if not (first == "_" or ("A" <= first <= "Z") or ("a" <= first <= "z")):
        return False
    return all(ch == "_" or ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9") for ch in key[1:])


def _strip_unquoted_comment(raw_value: str) -> str:
    # Only treat '#' as a comment delimiter when it is preceded by whitespace.
    for i in range(len(raw_value) - 1):
        if raw_value[i].isspace() and raw_value[i + 1] == "#":
            return raw_value[:i].rstrip()
    return raw_value.strip()


def _parse_quoted_value(raw_value: str) -> str:
    quote = raw_value[0]
    out: list[str] = []
    i = 1
    while i < len(raw_value):
        ch = raw_value[i]
        if ch == quote:
            return "".join(out)
        if ch == "\\" and i + 1 < len(raw_value):
            i += 1
            esc = raw_value[i]
            out.append(
                {
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                    "\\": "\\",
                    '"': '"',
                    "'": "'",
                }.get(esc, esc)
            )
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_dotenv_value(raw_value: str) -> str:
    raw_value = raw_value.strip()
    if not raw_value:
        return ""
    if raw_value[0] in {'"', "'"}:
        return _parse_quoted_value(raw_value)
    return _strip_unquoted_comment(raw_value)


def _parse_dotenv(content: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _is_valid_env_key(key):
            continue
        env[key] = _parse_dotenv_value(raw_value)
    return env


class _EnvironmentManager:
    def __init__(self, env_file: Path, logger: logging.Logger):
        self._env_file = env_file
        self._logger = logger
        self._baseline: dict[str, str | None] = {}
        self._current: dict[str, str] = {}
        self._last_digest: str | None = None

    def load_and_apply(self, *, reason: str) -> bool:
        try:
            content = self._env_file.read_text("utf-8")
        except FileNotFoundError:
            self._logger.warning("Environment file not found: %s", self._env_file)
            return False
        except (OSError, UnicodeDecodeError) as e:
            self._logger.warning("Failed to read environment file %s (%s)", self._env_file, e)
            return False

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        mapping = _parse_dotenv(content)

        if mapping == self._current:
            self._last_digest = digest
            return False

        prev_keys = set(self._current)
        new_keys = set(mapping)
        removed = prev_keys - new_keys
        added = new_keys - prev_keys
        changed = {k for k in prev_keys & new_keys if self._current[k] != mapping[k]}

        for key in removed:
            original = self._baseline.get(key)
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original

        for key, value in mapping.items():
            if key not in self._baseline:
                self._baseline[key] = os.environ.get(key)
            os.environ[key] = value

        self._current = mapping
        self._last_digest = digest

        self._logger.info(
            "Loaded environment file (%s): %s (vars=%d, changed=%d, added=%d, removed=%d)",
            reason,
            self._env_file,
            len(mapping),
            len(changed),
            len(added),
            len(removed),
        )
        return True


def mcp_server(target: str, *, environment: str | None = None, watch_debounce_ms: int | None = None, watch_step_ms: int | None = None):
    module, attr = target.rsplit(":", 1)

    from asyncio import Event, Lock, TaskGroup
    from contextlib import asynccontextmanager, contextmanager, suppress

    import mcp.server
    from fastmcp import FastMCP
    from fastmcp.server.proxy import ProxyClient
    from fastmcp.utilities.logging import get_logger
    from reactivity import async_effect, derived
    from reactivity.hmr.core import HMR_CONTEXT, AsyncReloader, _loader, get_path_module_map
    from reactivity.hmr.hooks import call_post_reload_hooks, call_pre_reload_hooks

    logger = get_logger(__name__)

    env_file: Path | None = None
    env_manager: _EnvironmentManager | None = None
    if environment is not None:
        env_file = Path(environment).expanduser()
        if not env_file.is_file():
            raise FileNotFoundError(f"Environment file not found: {env_file}")
        env_file = env_file.resolve()
        env_manager = _EnvironmentManager(env_file, logger)
        env_manager.load_and_apply(reason="startup")

    base_app = FastMCP(name="proxy", include_fastmcp_meta=False)

    @contextmanager
    def mount(app: FastMCP | mcp.server.FastMCP):
        base_app.mount(proxy := FastMCP.as_proxy(ProxyClient(app)), as_proxy=False)
        try:
            yield
        finally:  # unmount
            for mounted_server in list(base_app._mounted_servers):  # noqa: SLF001
                if mounted_server.server is proxy:
                    base_app._mounted_servers.remove(mounted_server)  # noqa: SLF001
                    # for older FastMCP versions
                    with suppress(AttributeError):
                        base_app._tool_manager._mounted_servers.remove(mounted_server)  # type: ignore  # noqa: SLF001
                        base_app._resource_manager._mounted_servers.remove(mounted_server)  # type: ignore  # noqa: SLF001
                        base_app._prompt_manager._mounted_servers.remove(mounted_server)  # type: ignore  # noqa: SLF001
                    break

    lock = Lock()

    async def using(app: FastMCP | mcp.server.FastMCP, stop_event: Event, finish_event: Event):
        async with lock:
            with mount(app):
                await stop_event.wait()
                finish_event.set()

    module_path = Path(module)
    server_origin: Path | None = None

    if module_path.is_file():  # path:attr
        server_origin = module_path.resolve()

        @derived(context=HMR_CONTEXT)
        def get_app():
            spec = ModuleSpec("server_module", _loader, origin=str(server_origin))
            m = module_from_spec(spec)
            _loader.exec_module(m)
            return getattr(m, attr)

    else:  # module:attr

        @derived(context=HMR_CONTEXT)
        def get_app():
            nonlocal server_origin
            m = import_module(module)
            if server_origin is None and isinstance((file := getattr(m, "__file__", None)), str):
                server_origin = Path(file).resolve()
            return getattr(m, attr)

    stop_event: Event | None = None
    finish_event: Event = ...  # type: ignore
    tg: TaskGroup = ...  # type: ignore

    @async_effect(context=HMR_CONTEXT, call_immediately=False)
    async def main():
        nonlocal stop_event, finish_event

        if stop_event is not None:
            stop_event.set()
            await finish_event.wait()

        app = get_app()

        tg.create_task(using(app, stop_event := Event(), finish_event := Event()))

    class Reloader(AsyncReloader):
        def __init__(self):
            super().__init__(".")
            self.error_filter.exclude_filenames.add(__file__)

        async def start_watching(self):
            from watchfiles import awatch

            watch_paths: list[str] = [self.entry, *self.includes]
            if env_file is not None:
                roots = [Path(p).resolve() for p in watch_paths]
                if not any(env_file.is_relative_to(r) for r in roots if r.is_dir()):
                    watch_paths.append(str(env_file))

            awatch_kwargs: dict[str, Any] = {"stop_event": self._stop_event}
            if watch_debounce_ms is not None:
                awatch_kwargs["debounce"] = watch_debounce_ms
            if watch_step_ms is not None:
                awatch_kwargs["step"] = watch_step_ms

            async for events in awatch(*watch_paths, **awatch_kwargs):
                self.on_events(events)

            del self._stop_event

        def on_changes(self, files: set[Path]):
            original_files = set(files)
            env_event = env_file is not None and env_file in original_files
            code_event_files = original_files - ({env_file} if env_file is not None else set())

            env_applied = False
            if env_event and env_manager is not None:
                env_applied = env_manager.load_and_apply(reason="change")
                if env_applied:
                    if server_origin is None:
                        logger.warning("Environment changed but target module path is not known yet; cannot force a reload.")
                    else:
                        files.add(server_origin)

            path2module = get_path_module_map()
            invalidating_code = sorted(code_event_files & set(path2module), key=lambda p: str(p))
            if env_applied:
                logger.info("Reload triggered by environment file change: %s", env_file)
            if invalidating_code:
                shown = invalidating_code[:5]
                suffix = "" if len(invalidating_code) <= 5 else f", +{len(invalidating_code) - 5} more"
                logger.info(
                    "Reload triggered by code changes (%d file(s)): %s%s",
                    len(invalidating_code),
                    ", ".join(map(str, shown)),
                    suffix,
                )

            return super().on_changes(files)

        async def __aenter__(self):
            call_pre_reload_hooks()
            try:
                await main()
            finally:
                call_post_reload_hooks()
                tg.create_task(self.start_watching())

        async def __aexit__(self, *_):
            self.stop_watching()
            main.dispose()
            if stop_event:
                stop_event.set()

    @asynccontextmanager
    async def _():
        nonlocal tg
        async with TaskGroup() as tg, Reloader():
            yield base_app

    return _()


async def run_with_hmr(
    target: str,
    log_level: str | None = None,
    transport="stdio",
    environment: str | None = None,
    watch_debounce_ms: int | None = None,
    watch_step_ms: int | None = None,
    **kwargs,
):
    async with mcp_server(target, environment=environment, watch_debounce_ms=watch_debounce_ms, watch_step_ms=watch_step_ms) as mcp:
        match transport:
            case "stdio":
                await mcp.run_stdio_async(show_banner=False, log_level=log_level)
            case "http" | "streamable-http":
                await mcp.run_http_async(log_level=log_level, **kwargs)
            case "sse":
                # for older FastMCP versions
                if hasattr(mcp, "run_sse_async"):
                    await mcp.run_sse_async(log_level=log_level, **kwargs)  # type: ignore
                else:
                    await mcp.run_http_async(transport="sse", log_level=log_level, **kwargs)
            case _:
                await mcp.run_async(transport, log_level=log_level, **kwargs)  # type: ignore


def cli(argv: list[str] = sys.argv[1:]):
    from argparse import SUPPRESS, ArgumentParser

    parser = ArgumentParser("mcp-hmr", description="Hot Reloading for MCP Servers • Automatically reload on code changes")
    if sys.version_info >= (3, 14):
        parser.suggest_on_error = True
    parser.add_argument("target", help="The import path of the FastMCP instance. Supports module:attr and path:attr")
    parser.add_argument("-t", "--transport", choices=["stdio", "http", "sse", "streamable-http"], default="stdio", help="Transport protocol to use (default: stdio)")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], type=str.upper, default=None)
    parser.add_argument("--environment", default=None, help="Path to a .env file to load and watch; changes trigger a reload of the target server module.")
    parser.add_argument("--watch-debounce-ms", type=int, default=None, help="Override watchfiles debounce in milliseconds (batching window).")
    parser.add_argument("--watch-step-ms", type=int, default=None, help="Override watchfiles step in milliseconds (polling granularity).")
    parser.add_argument("--host", default="localhost", help="Host to bind to for http/sse transports (default: localhost)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to for http/sse transports (default: 8000)")
    parser.add_argument("--path", default=None, help="Route path for the server (default: /mcp for http, /sse for sse)")
    parser.add_argument("--stateless", action="store_true", help="Shortcut for `stateless_http=True` and `json_response=True`")
    parser.add_argument("--no-cors", action="store_true", help="Disable CORS (the default is to enable CORS for all origins)")
    parser.add_argument("--version", action="version", version=f"mcp-hmr {__version__}", help=SUPPRESS)

    if not argv:
        parser.print_help()
        return

    args = parser.parse_args(argv)

    target: str = args.target

    if ":" not in target[1:-1]:
        parser.exit(1, f"The target argument must be in the format 'module:attr' (e.g. 'main:app') or 'path:attr' (e.g. './path/to/main.py:app'). Got: '{target}'")

    if args.environment is not None:
        env_file = Path(args.environment).expanduser()
        if not env_file.is_file():
            parser.exit(1, f"The environment file '{env_file}' not found. Please provide a valid file path.")
        args.environment = str(env_file.resolve())

    if args.watch_debounce_ms is not None and args.watch_debounce_ms < 0:
        parser.exit(1, "--watch-debounce-ms must be >= 0")
    if args.watch_step_ms is not None and args.watch_step_ms < 1:
        parser.exit(1, "--watch-step-ms must be >= 1")

    kwargs = args.__dict__

    if kwargs.pop("stateless"):
        if args.transport != "http":
            parser.exit(1, "--stateless can only be used with the http transport.")
        args.json_response = True
        args.stateless_http = True

    if kwargs.pop("no_cors"):
        if args.transport != "http":
            parser.exit(1, "--no-cors can only be used with the http transport.")
    elif args.transport == "http":
        from starlette.middleware import Middleware, cors

        args.middleware = [Middleware(cors.CORSMiddleware, allow_origins="*", allow_methods="*", allow_headers="*", expose_headers="*")]

    from asyncio import run
    from contextlib import suppress

    if (cwd := str(Path.cwd())) not in sys.path:
        sys.path.append(cwd)

    if (file := Path(module_or_path := target[: target.rindex(":")])).is_file():
        sys.path.insert(0, str(file.parent))
    else:
        if "." in module_or_path:  # find_spec may cause implicit imports of parent packages
            from reactivity.hmr.core import patch_meta_path

            patch_meta_path()

        if find_spec(module_or_path) is None:
            parser.exit(1, f"The target '{module_or_path}' not found. Please provide a valid module name or a file path.")

    with suppress(KeyboardInterrupt):
        run(run_with_hmr(**kwargs))


if __name__ == "__main__":
    cli()
