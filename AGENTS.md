# HMR - AGENTS.md

Updated from codebase reconnaissance on 2025-12-27 (initially generated 2025-12-25)

## Quick Reference

- Tech stack: Python (requires >=3.12) | uv workspace | ruff ~= 0.14.0 | pyright | watchfiles | uvicorn | werkzeug | fastapi | fastmcp | hmr ~= 0.7.0
- Key packages/entry points: `hmr` (core dependency + CLI), `uvicorn-hmr` (ASGI runner), `wsgi-hmr` (Werkzeug runner), `mcp-hmr` (FastMCP runner), `fastapi-reloader` (ASGI browser refresh), `hmr-reloader` (shared reload hub + WSGI helpers), `hmr-runner` (shared HMR orchestration), `hmr-daemon` (optional auto-imported background watcher)
- Setup (workspace venv): `uv sync --all-packages --locked`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type check: `uv run pyright`
- Build packages: `uv build --all-packages`

## Table of Contents

1. [Project Overview](#project-overview)
2. [Quick Start for Agents](#quick-start-for-agents)
3. [Core Commands](#core-commands)
4. [Project Structure](#project-structure)
5. [Architecture Overview](#architecture-overview)
6. [Development Patterns & Conventions](#development-patterns--conventions)
7. [Safety and Permissions](#safety-and-permissions)
8. [Code Examples](#code-examples)
9. [Git Workflow](#git-workflow)
10. [API Documentation](#api-documentation)
11. [Database](#database)
12. [Troubleshooting](#troubleshooting)

## Project Overview

This repository is a Python uv workspace that contains the HMR ecosystem packages (uvicorn-hmr, wsgi-hmr, mcp-hmr, fastapi-reloader, hmr-reloader, hmr-runner, hmr-daemon) plus runnable examples. The core "hmr" runtime is consumed as a dependency (see `hmr~=0.7.0`), while this repo focuses on integrations and demos.

Type: Python monorepo (uv workspace) with publishable packages under `packages/` and runnable examples under `examples/`
Status: Active development
Primary language(s): Python (>=3.12). Secondary: JavaScript (fastapi-reloader client snippet), JSON (MCP inspector config)

## Quick Start for Agents

### Orientation Checklist

Before making changes, ensure you understand:

- [ ] Which package owns what you are changing (see [Project Structure](#project-structure) and [Core Services Reference](#core-services-reference))
- [ ] The relevant entry point / CLI (see [Entry Points](#entry-points))
- [ ] The data/control flow you are affecting (see [Key Data Flows](#key-data-flows))
- [ ] The smallest runnable reproduction (prefer using `examples/*` when possible)

### Finding Your Way (3 hops)

- "Where is `mcp-hmr` implemented?" -> `packages/mcp-hmr/mcp_hmr.py:cli` -> `run_with_hmr()` / `mcp_server()`
- "Where is `uvicorn-hmr` implemented?" -> `packages/uvicorn-hmr/uvicorn_hmr.py:main` -> `run_slug_with_hmr()` -> `hmr_runner.run_with_hmr_async()`
- "How do I embed `uvicorn-hmr` programmatically?" -> `packages/uvicorn-hmr/uvicorn_hmr.py:run_with_hmr` -> `UvicornHMRConfig` / `UvicornHMRHooks` (aliases of `hmr_runner.HMRConfig` / `hmr_runner.HMRHooks`)
- "Where is `wsgi-hmr` implemented?" -> `packages/wsgi-hmr/wsgi_hmr.py:main` -> `run_slug_with_hmr()` -> `hmr_runner.run_with_hmr_async()`
- "Where is the shared HMR orchestration implemented?" -> `packages/hmr-runner/hmr_runner.py:run_with_hmr_async` -> `HMRConfig` / `_compile_asset_spec()`
- "Where does browser auto-refresh come from?" -> `packages/fastapi-reloader/fastapi_reloader/patcher.py` (ASGI HTML injection) + `packages/hmr-reloader/hmr_reloader/_hub.py` (reload hub) + `packages/hmr-reloader/hmr_reloader/wsgi.py` (WSGI injection + endpoint)
- "Why is a background watcher thread running?" -> check `hmr-daemon` install and `packages/hmr-daemon/hmr_daemon_.pth` (disable with `NO_HMR_DAEMON=1`)

## Core Commands

All commands in this file are intended to be run from the repo root unless stated otherwise. Prefer `uv run ...` over calling `python` directly, since your system `python3` may not satisfy the project's required Python version.

### Environment and Setup

- Sync the workspace environment (creates/updates `.venv/`):
  - `uv sync --all-packages --locked`
- Show the interpreter uv selected:
  - `uv run python --version`

### Linting, Formatting, Type Checking

File-scoped (preferred):

- Lint one file: `uv run ruff check packages/mcp-hmr/mcp_hmr.py`
- Format one file: `uv run ruff format packages/mcp-hmr/mcp_hmr.py`
- Type check one file: `uv run pyright packages/mcp-hmr/mcp_hmr.py`

Workspace-wide:

- Lint all: `uv run ruff check .`
- Format all: `uv run ruff format .`
- Type check all: `uv run pyright`

### Build (Packaging)

Build outputs go to `dist/` (gitignored via `.gitignore`).

- Build all workspace packages (sdist + wheel): `uv build --all-packages`
- Build a single package: `uv build --package mcp-hmr`

### Smoke Checks (Fast)

- Byte-compile everything quickly: `uv run python -m compileall -q packages examples`
- Show installed entrypoints help:
  - `uv run hmr --help`
  - `uv run uvicorn-hmr --help`
  - `uv run wsgi-hmr --help`
  - `uv run mcp-hmr --help`

### Run the Included Examples

These examples are uv workspace members, so after `uv sync --all-packages --locked` you can run them from their directories without creating separate venvs.

Demo (basic script):

- `cd examples/demo && uv run hmr entry.py`

FastAPI example (ASGI server with hot reloading):

- `cd examples/fastapi && uv run uvicorn-hmr main:app`
- Enable browser auto-refresh (requires fastapi-reloader): `cd examples/fastapi && uv run uvicorn-hmr main:app --refresh`

Flask example (WSGI, uses helper bootstrap in `start.py`):

- `cd examples/flask && uv run hmr app.py`

MCP example:

- Run the server directly (stdio transport by default): `cd examples/mcp && uv run mcp-hmr main.py:app`
- Run with HTTP transport: `cd examples/mcp && uv run mcp-hmr main.py:app -t http --port 8000 --path /mcp`
- Run the demo client (loops until interrupted): `cd examples/mcp && uv run python client.py`

## Project Structure

```
/
|-- pyproject.toml                 # uv workspace members + ruff/pyright configuration
|-- uv.lock                        # workspace lockfile
|-- packages/
|   |-- hmr-reloader/
|   |   |-- hmr_reloader/          # shared reload hub + runtime injection + WSGI middleware
|   |   `-- pyproject.toml
|   |-- mcp-hmr/
|   |   |-- mcp_hmr.py             # CLI + programmatic API (`mcp_server`, `run_with_hmr`)
|   |   `-- pyproject.toml         # `mcp-hmr` console script
|   |-- hmr-runner/
|   |   |-- hmr_runner.py          # shared in-process HMR runner (used by uvicorn-hmr, wsgi-hmr)
|   |   `-- pyproject.toml
|   |-- uvicorn-hmr/
|   |   |-- uvicorn_hmr.py         # Typer CLI + uvicorn integration (delegates to hmr-runner)
|   |   `-- pyproject.toml         # `uvicorn-hmr` console script
|   |-- fastapi-reloader/
|   |   |-- fastapi_reloader/
|   |   |   |-- core.py            # reload signal endpoints
|   |   |   |-- patcher.py         # middleware + HTML injection
|   |   |   `-- runtime.js         # injected client snippet
|   |   `-- pyproject.toml
|   |-- wsgi-hmr/
|   |   |-- wsgi_hmr.py            # Typer CLI + Werkzeug runner (delegates to hmr-runner)
|   |   `-- pyproject.toml
|   `-- hmr-daemon/
|       |-- hmr_daemon_.pth        # auto-import hook (starts daemon on interpreter startup)
|       |-- hmr_daemon/            # platform-specific daemon code
|       `-- pyproject.toml
`-- examples/
    |-- demo/                      # minimal hot reload demo (`hmr entry.py`)
    |-- fastapi/                   # uvicorn-hmr demo server
    |-- flask/                     # Flask + hmr demo
    `-- mcp/                       # mcp-hmr demo + inspector config (`mcp.json`)
```

## Architecture Overview

### Entry Points

| Entry Point | Purpose | What It Initializes |
|-------------|---------|---------------------|
| `mcp-hmr` (`packages/mcp-hmr/mcp_hmr.py:cli`) | Run a FastMCP server with hot reload | argparse CLI, optional `.env` loading/watching (`--environment`), code reloading via `reactivity.hmr.*`, selected transport (stdio/http/sse/streamable-http) |
| `uvicorn-hmr` (`packages/uvicorn-hmr/uvicorn_hmr.py:app`) | Run Uvicorn with hot reload restarts | Typer CLI, delegates to `hmr-runner`, uvicorn `Server`, optional browser refresh + asset refresh-only watching |
| `wsgi-hmr` (`packages/wsgi-hmr/wsgi_hmr.py:app`) | Run a Werkzeug dev server with hot reload restarts | Typer CLI, delegates to `hmr-runner`, Werkzeug server, optional browser refresh + asset refresh-only watching |
| `.pth` hook (`packages/hmr-daemon/hmr_daemon_.pth`) | Optional daemon auto-start on interpreter startup | imports `hmr_daemon`, which imports `hmr_daemon.posix`/`hmr_daemon.windows` unless `NO_HMR_DAEMON=1` |
| Examples (`examples/*`) | Runnable demos | minimal scripts and apps consuming the packages above |

### Core Services Reference

#### `mcp-hmr` (`packages/mcp-hmr/mcp_hmr.py`)

Purpose: Hot reload wrapper for FastMCP servers (CLI + programmatic API).

Key call surfaces:

- `mcp_server(target: str, *, environment: str | None = None, watch_debounce_ms: int | None = None, watch_step_ms: int | None = None)` - async context manager yielding a proxy `FastMCP` app that swaps the mounted target app on reload; optionally loads and watches a `.env` file and configures watchfiles batching.
- `run_with_hmr(target: str, log_level: str | None = None, transport="stdio", environment: str | None = None, watch_debounce_ms: int | None = None, watch_step_ms: int | None = None, **kwargs)` - run with selected transport; forwards `environment` and watch batching knobs into `mcp_server(...)`.
- `cli(argv: list[str] = sys.argv[1:])` - console entrypoint (`mcp-hmr`).

Dependencies: `fastmcp>=2.2.0,<3`, `hmr~=0.7.0` (`reactivity.hmr.*`).

Used by: `examples/mcp`, external consumers embedding an MCP server runner.

#### `hmr-runner` (`packages/hmr-runner/hmr_runner.py`)

Purpose: Shared in-process HMR orchestration used by `uvicorn-hmr` and `wsgi-hmr`.

Key call surfaces:

- `HMRConfig(...)` - shared configuration for reload/watch behavior:
  - `reload_include` / `reload_exclude`
  - `watch_debounce_ms` / `watch_step_ms` (watchfiles batching knobs)
  - `restart_cooldown_ms` (rate-limit restarts)
  - `asset_refresh_include` / `asset_refresh_exclude` (refresh-only watching when `refresh=True` and a refresh callback is provided)
- `HMRHooks(...)` - lifecycle hooks (`on_change_detected`, `before_shutdown`, `after_shutdown`, `before_reload`, `after_reload`, `on_server_created`, `on_server_stopped`)
- `run_with_hmr(...)` / `run_with_hmr_async(...)` - embed a server by providing `load_app()` and `make_server(app)`; optional `refresh_callback` and `force_restart_files`.

Dependencies: `hmr~=0.7.0` (`reactivity.hmr.*`), `watchfiles` (used for file watching).

Used by: `uvicorn-hmr`, `wsgi-hmr`.

#### `uvicorn-hmr` (`packages/uvicorn-hmr/uvicorn_hmr.py`)

Purpose: Uvicorn runner that restarts on file changes; delegates the reload loop to `hmr-runner`; optional browser refresh via `fastapi-reloader`.

Key call surfaces:

- `app` - Typer application (console entrypoint `uvicorn-hmr`).
- `main(...)` - Typer command implementing the reload/restart loop.
- `run_with_hmr(...)` / `run_with_hmr_async(...)` - programmatic embedding (re-exported from `hmr_runner`; provide `load_app()` and `make_server(app)`).
- `run_slug_with_hmr("module:attr", ...)` - slug-based wrapper (wires uvicorn server + config and calls `run_with_hmr(...)`).
- `UvicornHMRConfig` / `UvicornHMRHooks` - aliases of `hmr_runner.HMRConfig` / `hmr_runner.HMRHooks`.
- `_try_patch(app)` / `_try_refresh()` - bridge to `fastapi-reloader` (only when `--refresh` is enabled).

Dependencies: `hmr~=0.7.0` (`reactivity.hmr.*`), `hmr-runner>=0.1.0,<1`, `uvicorn>=0.24.0`, `typer-slim>=0.15.4,<1`; optional `fastapi-reloader~=1.x` via `uvicorn-hmr[all]`.

Used by: `examples/fastapi`.

#### `wsgi-hmr` (`packages/wsgi-hmr/wsgi_hmr.py`)

Purpose: Werkzeug development server runner for WSGI apps (Flask, etc) with in-process hot reload; delegates the reload loop to `hmr-runner`; optional browser refresh via `hmr-reloader` WSGI injection.

Key call surfaces:

- `app` - Typer application (console entrypoint `wsgi-hmr`).
- `main(...)` - Typer command implementing the reload/restart loop.
- `run_with_hmr(...)` / `run_with_hmr_async(...)` - programmatic embedding (re-exported from `hmr_runner`).
- `run_slug_with_hmr("module:attr", ...)` - slug-based wrapper (wires Werkzeug server + config and calls `run_with_hmr(...)`).
- `WSGIHMRConfig` / `WSGIHMRHooks` - aliases of `hmr_runner.HMRConfig` / `hmr_runner.HMRHooks`.

Dependencies: `hmr-reloader>=0.1.0,<1`, `hmr-runner>=0.1.0,<1`, `werkzeug>=3.0.0,<4`, `typer-slim>=0.15.4,<1`.

Used by: external WSGI apps; useful for `examples/flask` style setups.

#### `hmr-reloader` (`packages/hmr-reloader/hmr_reloader`)

Purpose: Shared browser reload signaling and WSGI helpers (stdlib-only) used by `fastapi-reloader` and `wsgi-hmr`.

Public API (re-exported in `packages/hmr-reloader/hmr_reloader/__init__.py`):

- Reload hub:
  - `send_reload_signal()`
  - `subscription()` (async subscription generator)
- Runtime injection:
  - `RUNTIME_JS`
  - `INJECTION` (the HTML snippet appended to responses)
- WSGI helpers:
  - `RELOADER_PATH` (default path)
  - `wsgi_reloader_endpoint`
  - `wsgi_reloader_route_middleware`
  - `wsgi_html_injection_middleware`
  - `wsgi_auto_refresh_middleware`

Used by: `fastapi-reloader` (ASGI wrapper), `wsgi-hmr` (Werkzeug runner).

#### `fastapi-reloader` (`packages/fastapi-reloader/fastapi_reloader`)

Purpose: HTML injection + a simple long-polling endpoint for client refresh.

Public API (re-exported in `packages/fastapi-reloader/fastapi_reloader/__init__.py`):

- `patch_for_auto_reloading(app)`
- `send_reload_signal()`
- `html_injection_middleware`
- `reloader_route_middleware`
- `auto_refresh_middleware`

Endpoints: `/---fastapi-reloader---` (see `packages/fastapi-reloader/fastapi_reloader/core.py`).

Dependencies: `fastapi~=0.115`, `asgi-lifespan~=2.0`, `hmr-reloader>=0.1.0,<1`.

Used by: `uvicorn-hmr` when `--refresh` is enabled.

#### `hmr-daemon` (`packages/hmr-daemon`)

Purpose: Optional background watcher started via `.pth` auto-import.

Key behavior:

- Installed `.pth` runs `import hmr_daemon` on interpreter startup.
- `hmr_daemon/__init__.py` starts the daemon unless `NO_HMR_DAEMON=1`.

### Key Data Flows

#### Flow: `uvicorn-hmr` reload loop (with `--refresh` and optional asset refresh-only watching)

```
uvicorn-hmr main:app --refresh --asset-include webui --env-file .env
  -> packages/uvicorn-hmr/uvicorn_hmr.py:main
     - resolve slug to a module file
     - ensure target module is not already imported
     - create a uvicorn Server factory (and optionally patch for browser refresh)
     - delegate hot reload orchestration to hmr_runner.run_with_hmr_async(...)
  -> packages/hmr-runner/hmr_runner.py:run_with_hmr_async
     - watchfiles.awatch(..., debounce=watch_debounce_ms, step=watch_step_ms)
     - classify changes:
       - asset-only hits (when --refresh + --asset-include/--asset-exclude): call refresh_callback (no server restart)
       - code hits / tracked file hits / forced restart files (e.g. --env-file): graceful shutdown and restart loop
     - optional restart pacing: restart_cooldown_ms rate-limits server starts
```

#### Flow: `wsgi-hmr` reload loop (Werkzeug, with `--refresh` and optional asset refresh-only watching)

```
wsgi-hmr main:app --refresh --asset-include webui
  -> packages/wsgi-hmr/wsgi_hmr.py:main
     - resolve slug to a module file
     - ensure target module is not already imported
     - optionally wrap the WSGI app with hmr_reloader.wsgi_auto_refresh_middleware
     - delegate hot reload orchestration to hmr_runner.run_with_hmr_async(...)
```

#### Flow: `mcp-hmr` http transport with a watched environment file

```
mcp-hmr examples/mcp/main.py:app -t http --port 8000 --path /mcp --environment .env --watch-debounce-ms 2500 --watch-step-ms 100
  -> packages/mcp-hmr/mcp_hmr.py:cli (argparse + validation)
  -> run_with_hmr(...)
     -> mcp_server(...)
        - load/apply `.env` (and re-apply on change); changes force a reload of the target server module
        - watchfiles batching configured via watch_debounce_ms / watch_step_ms
        - mounts a proxy `FastMCP` app and swaps the mounted target app on reload
     -> mcp.run_http_async(...)
```

#### Flow: browser auto-refresh (fastapi-reloader)

```
HTML GET response
  -> html_injection_middleware / _injection_http_middleware
     - only injects for GET + content-type includes html + content-encoding identity
Client connects to /---fastapi-reloader---
  -> send_reload_signal() pushes "1\\n" to subscribers, browser refreshes
```

### Module Architecture

```
hmr (dependency; provides reactivity.hmr.*)
  |
  +-- packages/hmr-runner (shared reload/restart orchestration + asset refresh-only watching)
  |     +-- used by: packages/uvicorn-hmr, packages/wsgi-hmr
  |
  +-- packages/hmr-reloader (shared browser reload hub + runtime injection + WSGI helpers)
  |     +-- used by: packages/fastapi-reloader, packages/wsgi-hmr
  |
  +-- packages/uvicorn-hmr (CLI + uvicorn integration; delegates to hmr-runner)
  |     +-- optional: packages/fastapi-reloader (ASGI browser refresh)
  |
  +-- packages/wsgi-hmr (CLI + Werkzeug integration; delegates to hmr-runner + uses hmr-reloader)
  |
  +-- packages/mcp-hmr (CLI + FastMCP proxy integration)
  |
  +-- packages/hmr-daemon (.pth auto-import side effect)
  |
  +-- examples/* (demos consuming the above)
```

### Critical Paths and Hot Spots

- `packages/hmr-runner/hmr_runner.py`: reload loop, asset refresh classification, restart cooldown, ReactiveModule monkey-patching (sensitive code).
- `packages/uvicorn-hmr/uvicorn_hmr.py`: CLI wiring, uvicorn Server integration, `--env-file` forced restart behavior.
- `packages/wsgi-hmr/wsgi_hmr.py`: Werkzeug server wrapper, refresh injection, CLI wiring.
- `packages/mcp-hmr/mcp_hmr.py`: target loading (module vs path), `.env` watching, watch batching knobs, transport branching.
- `packages/hmr-reloader/hmr_reloader/wsgi.py`: WSGI injection + endpoint (`/---fastapi-reloader---`).
- `packages/fastapi-reloader/fastapi_reloader/patcher.py`: ASGI HTML injection conditions and response mutation.
- `packages/hmr-daemon/hmr_daemon_.pth` + `packages/hmr-daemon/hmr_daemon/__init__.py`: auto-import and background thread side effects.

### Key Utilities and Reuse

- Use `fastapi_reloader.patch_for_auto_reloading(app)` instead of custom HTML injection.
- For shared orchestration (embedding custom servers), use `hmr_runner.run_with_hmr(...)` / `run_with_hmr_async(...)` with `hmr_runner.HMRConfig`.
- For WSGI refresh injection and signaling, use `hmr_reloader.wsgi_auto_refresh_middleware` and `hmr_reloader.send_reload_signal()`.
- Use `mcp_hmr.run_with_hmr(...)` for programmatic embedding rather than re-implementing transport selection.
- Use `uvicorn_hmr.run_with_hmr(...)` / `run_with_hmr_async(...)` for programmatic embedding with a custom `uvicorn.Config`/`uvicorn.Server`.
- Prefer `Path(...).resolve()` and `Path.read_text("utf-8")` patterns already used in `mcp_hmr.py`.

## Development Patterns & Conventions

### Style and Tooling

- Python version: requires >= 3.12 (`requires-python = ">=3.12"` across workspace projects)
- Formatting and linting: ruff (workspace dependency is `ruff~=0.14.0`, see `pyproject.toml`)
  - line length: 200
  - many lint rules are enabled; avoid unnecessary `# type: ignore` (pyright is configured to error on unnecessary ignores)
- Type checking: pyright (see `[tool.pyright]` in `pyproject.toml`)

### Common Code Patterns in This Repo

- Prefer `pathlib.Path` for filesystem operations (`Path(...).resolve()`, `Path.read_text()`)
- Prefer modern typing syntax (PEP 604 unions like `Path | None`, builtin generics like `list[str]`)
- CLIs are implemented with:
  - `argparse` (mcp-hmr)
  - `typer` (uvicorn-hmr, wsgi-hmr)
- Hot reloading is implemented via the `reactivity.hmr.*` APIs (import hooks, reactive modules, file watching)

### Gotchas and Project-Specific Constraints

- System `python3` may be too old. Use `uv run python ...` for all executions in this repo.
- `uvicorn-hmr` requires that the target module is not already imported as a normal module. If you imported it, you must patch the import machinery before import (see message in `packages/uvicorn-hmr/uvicorn_hmr.py`).
- `uvicorn-hmr` differs from uvicorn in reload include/exclude semantics:
  - it expects literal paths, not glob patterns
  - it only includes/excludes the paths you specify (not all Python files implicitly)
  - default `reload_exclude` includes `.venv`
- `uvicorn-hmr` and `wsgi-hmr` support refresh-only watching (when `--refresh` is enabled):
  - `--asset-include` / `--asset-exclude` accept directory roots, files, or globs (matched relative to the current working directory; absolute patterns are also accepted)
  - excludes win
  - `*.py` is always treated as code (never as an asset refresh trigger)
- `uvicorn-hmr` / `wsgi-hmr` watch batching and restart pacing:
  - `--watch-debounce-ms` / `--watch-step-ms` tune watchfiles coalescing
  - `--restart-cooldown-ms` rate-limits server restarts (changes are still applied; restarts are queued until the cooldown expires)
- `uvicorn-hmr --env-file` is treated as a forced-restart file (watched, and changes trigger a restart even if refresh-only asset watching is configured).
- `fastapi-reloader` injects a script into HTML responses:
  - only for GET responses with `content-type` containing "html"
  - only when `content-encoding` is identity (put it before compression middleware)
  - safe to add in multiple places; it guards against double injection
- `mcp-hmr` supports watch batching knobs for its internal watchfiles loop:
  - `--watch-debounce-ms` / `--watch-step-ms` (also available programmatically via `mcp_server(..., watch_debounce_ms=..., watch_step_ms=...)`)
- `hmr-daemon` is activated via a `.pth` file (`packages/hmr-daemon/hmr_daemon_.pth`):
  - installing it can start a background watcher thread as a side-effect
  - disable by setting `NO_HMR_DAEMON=1` in the environment
  - tune watch coalescing via `HMR_DAEMON_DEBOUNCE_MS` (>= 0) and `HMR_DAEMON_STEP_MS` (>= 1)
- HMR caveat: circular dependencies in some edge cases may still cause unexpected behavior; use extra caution if you have lots of code in `__init__.py` (see repo root `README.md`).

## Safety and Permissions

### Allowed Without Asking

- Read any file in the repository
- Run read-only commands (`git status`, `git diff`, `uv run ... --help`)
- Run file-scoped lint/format/type-check commands
- Add or update Python code and documentation (including `AGENTS.md`) in this repo

### Ask Before Executing

- Adding/upgrading dependencies or changing lockfiles (`pyproject.toml`, `uv.lock`)
- Deleting files or directories
- Changing packaging metadata or release versions in `packages/*/pyproject.toml`
- Publishing packages to an external registry (PyPI)
- Starting long-running servers on default ports (confirm port/host first if running on a shared machine)

### Never Do Without Explicit Override

- Commit or print secrets (API keys, tokens, private keys)
- Disable linting/type checking by weakening configs to "make it pass"
- Bypass authentication/authorization logic in example servers
- Force-push, rewrite git history, or perform destructive git operations

## Code Examples

The snippets below are copied from the current codebase. Use the "GOOD" patterns as templates; treat the "AVOID" patterns as low-level internals that should not spread into normal application code unless you are explicitly working on the HMR integration layer.

### GOOD: Safe HTML injection with guardrails (fastapi-reloader)

From `packages/fastapi-reloader/fastapi_reloader/patcher.py`:

```python
async def _injection_http_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    res = await call_next(request)

    if request.scope.get(FLAG) or request.method != "GET" or "html" not in (res.headers.get("content-type", "")) or res.headers.get("content-encoding", "identity") != "identity":
        return res

    request.scope[FLAG] = True
```

### GOOD: Explicit CLI input validation (mcp-hmr)

From `packages/mcp-hmr/mcp_hmr.py`:

```python
if ":" not in target[1:-1]:
    parser.exit(1, f"The target argument must be in the format 'module:attr' (e.g. 'main:app') or 'path:attr' (e.g. './path/to/main.py:app'). Got: '{target}'")
```

### GOOD: "Not imported yet" safety check (uvicorn-hmr)

From `packages/uvicorn-hmr/uvicorn_hmr.py`:

```python
resolved = _resolve_slug(slug)
if resolved.module in sys.modules:
    raise RuntimeError(f"It seems you've already imported `{resolved.module}` as a normal module. You should call `reactivity.hmr.core.patch_meta_path()` before it.")
```

### AVOID: Reaching into private internals for compatibility (mcp-hmr)

From `packages/mcp-hmr/mcp_hmr.py` (only do this when you have no public API alternative):

```python
for mounted_server in list(base_app._mounted_servers):  # noqa: SLF001
    if mounted_server.server is proxy:
        base_app._mounted_servers.remove(mounted_server)  # noqa: SLF001
```

### AVOID: Private attribute access and monkey-patching (hmr-runner)

From `packages/hmr-runner/hmr_runner.py` (low-level HMR integration code):

```python
__load = ReactiveModule.__load if TYPE_CHECKING else ReactiveModule._ReactiveModule__load  # noqa: SLF001
```

### AVOID: Global monkey-patching via `.pth` and import side effects (hmr-daemon)

From `packages/hmr-daemon/hmr_daemon/__init__.py` and `packages/hmr-daemon/hmr_daemon_.pth`:

```python
# hmr_daemon_.pth
import hmr_daemon
```

```python
if "NO_HMR_DAEMON" not in os.environ:
    from threading import enumerate

    if all(t.name != "hmr-daemon" for t in enumerate()):
        if os.name == "nt":
            from . import windows  # noqa: F401
        else:
            from . import posix  # noqa: F401
```

## Git Workflow

No CI workflows and no `CONTRIBUTING.md` were found in this repository. Use a conservative workflow:

- Keep changes scoped to one package/example when possible
- Before opening a PR, run:
  - `uv sync --all-packages --locked`
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run pyright`
  - `uv run python -m compileall -q packages examples`
  - `uv build --all-packages`

## API Documentation

This repo primarily exposes CLI entrypoints and small programmatic surfaces.

### mcp-hmr

- CLI: `mcp-hmr <target> [options]`
  - target formats:
    - `module:attr` (example: `main:app`)
    - `path/to/file.py:attr` (example: `./server/main.py:app`)
  - transports: `stdio` (default), `http`, `sse`, `streamable-http`
  - notable flags (see `packages/mcp-hmr/mcp_hmr.py:cli`):
    - `--transport/-t` (choices above)
    - `--log-level/-l` (`DEBUG|INFO|WARNING|ERROR|CRITICAL`)
    - `--environment` (path to a `.env` file to load and watch; changes force a reload of the target server module)
    - `--watch-debounce-ms` / `--watch-step-ms` (override watchfiles batching)
    - `--host`, `--port`, `--path`
    - `--stateless` (http only; sets `stateless_http=True` and `json_response=True`)
    - `--no-cors` (http only; disables default permissive CORS middleware)
- Programmatic:
  - `mcp_hmr.mcp_server(target: str, environment: str | None = None, watch_debounce_ms: int | None = None, watch_step_ms: int | None = None)` (async context manager yielding a proxy server)
  - `mcp_hmr.run_with_hmr(target: str, transport=..., log_level=..., environment=..., watch_debounce_ms=..., watch_step_ms=..., **kwargs)`

### uvicorn-hmr

- CLI: `uvicorn-hmr [slug] [--reload-include ...] [--reload-exclude ...] [--asset-include ...] [--asset-exclude ...] [--watch-debounce-ms ...] [--watch-step-ms ...] [--restart-cooldown-ms ...] [--host ...] [--port ...] [--log-level ...] [--env-file ...] [--refresh] [--clear]`
  - slug format is the uvicorn style `module:attr`
  - `--refresh` enables browser page auto-refresh via `fastapi-reloader`
  - `--asset-include` / `--asset-exclude` enable refresh-only watching (requires `--refresh`)
  - `--watch-debounce-ms` / `--watch-step-ms` override watchfiles batching
  - `--restart-cooldown-ms` rate-limits restarts
  - `--reload` exists as a hidden deprecated alias for `--refresh` (backward compatibility)
- Programmatic:
  - `uvicorn_hmr.run_with_hmr(entry=..., load_app=..., make_server=..., hmr=UvicornHMRConfig(...), hooks=UvicornHMRHooks(...))`
  - `uvicorn_hmr.run_with_hmr_async(...)`
  - `uvicorn_hmr.run_slug_with_hmr("module:attr", ...)`

### wsgi-hmr

- CLI: `wsgi-hmr [slug] [--reload-include ...] [--reload-exclude ...] [--asset-include ...] [--asset-exclude ...] [--watch-debounce-ms ...] [--watch-step-ms ...] [--restart-cooldown-ms ...] [--host ...] [--port ...] [--refresh] [--clear]`
  - slug format is the uvicorn style `module:attr`
  - `--refresh` enables browser page auto-refresh (WSGI injection + `/---fastapi-reloader---` endpoint)
  - `--asset-include` / `--asset-exclude` enable refresh-only watching (requires `--refresh`)
- Programmatic:
  - `wsgi_hmr.run_with_hmr(entry=..., load_app=..., make_server=..., hmr=WSGIHMRConfig(...), hooks=WSGIHMRHooks(...))`
  - `wsgi_hmr.run_with_hmr_async(...)`
  - `wsgi_hmr.run_slug_with_hmr("module:attr", ...)`

### hmr-runner

- Programmatic-only shared runner used by `uvicorn-hmr` and `wsgi-hmr`:
  - `hmr_runner.HMRConfig` (includes watch batching knobs, restart cooldown, and asset refresh-only watching specs)
  - `hmr_runner.HMRHooks`
  - `hmr_runner.run_with_hmr(...)` / `hmr_runner.run_with_hmr_async(...)`

### hmr-reloader

- Shared browser reload hub + WSGI injection helpers used by `fastapi-reloader` and `wsgi-hmr`:
  - `hmr_reloader.send_reload_signal()` / `hmr_reloader.subscription()`
  - `hmr_reloader.RELOADER_PATH` (defaults to `/---fastapi-reloader---`)
  - `hmr_reloader.wsgi_auto_refresh_middleware`

### fastapi-reloader

- Injects a small client snippet into HTML responses and exposes endpoints under `/---fastapi-reloader---`.
- Public API (see `packages/fastapi-reloader/fastapi_reloader/__init__.py`):
  - `auto_refresh_middleware`
  - `html_injection_middleware`
  - `reloader_route_middleware`
  - `patch_for_auto_reloading`
  - `send_reload_signal`

### hmr-daemon

- Installed via `.pth` auto-import; starts a background watcher unless disabled via `NO_HMR_DAEMON=1`.
- Watch tuning: `HMR_DAEMON_DEBOUNCE_MS` (>= 0) and `HMR_DAEMON_STEP_MS` (>= 1)

## Database

No database is used by this repository itself (no ORM, migrations, or schema directory). The included examples are for hot-reload and server integration demos.

## Troubleshooting

### Wrong Python Version / Import Errors

- Do not use system `python3` for this repo.
- Always prefer: `uv run python ...`
- If `uv run python --version` is < 3.12, make sure `python3.12` is installed or allow uv to download a managed Python.

### `uvicorn-hmr` Does Not Reload

- If your target module was imported already, the import hook patching will not take effect. Ensure the module is not imported before starting `uvicorn-hmr`.
- If you pass `--reload-include` / `--reload-exclude`, use literal paths (not globs).

### `uvicorn-hmr --refresh` Fails

- `uvicorn-hmr --refresh` requires `fastapi-reloader` (install via `uv sync --all-packages --locked`, or `pip install uvicorn-hmr[all]` outside the workspace).

### `wsgi-hmr --refresh` Notes

- `wsgi-hmr --refresh` uses WSGI injection and the `/---fastapi-reloader---` endpoint via `hmr-reloader` (no extra dependency like `fastapi-reloader`).
- It only makes sense for HTML responses (it injects a small client runtime into HTML).

### Asset Refresh-Only Watching Does Not Work

- Asset refresh-only behavior requires `--refresh` plus at least one `--asset-include` entry.
- `--asset-include` / `--asset-exclude` accept directory roots, files, or globs. Excludes win.
- `*.py` is always treated as code, so Python edits will restart the server (not just refresh the browser).

### Too Many Restarts (Coalesce Changes)

- Tune watchfiles batching with `--watch-debounce-ms` and `--watch-step-ms`.
- Rate-limit restarts with `--restart-cooldown-ms` (changes are still applied; restarts are queued until the cooldown expires).

### `fastapi-reloader` Script Injection Not Working

- Ensure responses are not compressed (it checks `content-encoding == identity`).
- Put `html_injection_middleware` before compression middleware (GZip/Brotli/etc.).

### `fastapi-reloader` Standalone Server Hangs on Shutdown

If you use `fastapi-reloader` without `uvicorn-hmr`, you must call `send_reload_signal()` during your ASGI server shutdown hook. Otherwise, the long-poll connection can prevent the server from shutting down gracefully (see `packages/fastapi-reloader/README.md`).

### MCP HTTP CORS

- For `mcp-hmr -t http`, CORS is permissive by default for development convenience. Disable with `--no-cors` if needed.
