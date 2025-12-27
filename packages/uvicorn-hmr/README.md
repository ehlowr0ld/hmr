# uvicorn-hmr

[![PyPI - Version](https://img.shields.io/pypi/v/uvicorn-hmr)](https://pypi.org/project/uvicorn-hmr/)
[![PyPI - Downloads](https://img.shields.io/pypi/dw/uvicorn-hmr)](https://pepy.tech/projects/uvicorn-hmr)

This package provides hot module reloading (HMR) for [`uvicorn`](https://github.com/encode/uvicorn).

It uses [`watchfiles`](https://github.com/samuelcolvin/watchfiles) to detect FS modifications,
re-executes the corresponding modules with [`hmr`](https://github.com/promplate/pyth-on-line/tree/main/packages/hmr) and restart the server (in the same process).

**HOT** means the main process never restarts, and reloads are fine-grained (only the changed modules and their dependent modules are reloaded).
Since the python module reloading is on-demand and the server is not restarted on every save, it is much faster than the built-in `--reload` option provided by `uvicorn`.

## Why?

1. When you use [`uvicorn --reload`](https://uvicorn.dev/settings/?h=reload#development), it restarts the whole process on every file change, but restarting the whole process is unnecessary:
   - There is no need to restart the Python interpreter, neither all the 3rd-party packages you imported.
   - Your changes usually affect only one single file, the rest of your application remains unchanged.
2. [`hmr`](https://pyth-on-line.promplate.dev/hmr) tracks dependencies at runtime, remembers the relationships between your modules and only reruns necessary modules.
3. Since [v0.7](https://github.com/promplate/pyth-on-line/releases/tag/hmr/v0.7.0), `hmr` also tracks file system access - any file your code reads (config files, templates, data files, etc.) becomes reactive and will trigger reloads when modified.
4. So you can save a lot of time by not restarting the whole process on every file change. You can see a significant speedup for debugging large applications.
5. Although magic is involved, we thought and tested them very carefully, so everything works just as-wished.
   - Your lazy loading through module-level `__getattr__` still works
   - Your runtime imports through `importlib.import_module` or even `__import__` still work
   - Even valid circular imports between `__init__.py` and sibling modules still work
   - Fine-grained dependency tracking in the above cases still work
   - Decorators still work, even meta programming hacks like `getsource` calls work too
   - Standard dunder metadata like `__name__`, `__doc__`, `__file__`, `__package__` are correctly set
   - ASGI lifecycles are preserved
6. We did some elegant engineering to optimize UX and performance of `uvicorn`:
   - Since the reloader and the server stay in the same thread, we can gracefully wait for the server to shutdown before reloading, which avoids long weird tracebacks that you will see when you keep pressing save during `uvicorn --reload`.
   - `uvicorn`'s main loop has a 100ms tick interval, we optimized it into an event-driven model, so the server can respond to shutdown calls instantly!

Normally, you can replace `uvicorn --reload` with `uvicorn-hmr` and everything will work as expected, with a much faster refresh experience.

## Installation

```sh
pip install uvicorn-hmr
```

<details>

<summary> Or with extra dependencies: </summary>

```sh
pip install uvicorn-hmr[all]
```

This will also install [`fastapi-reloader`](../fastapi-reloader/), enabling the `--refresh` flag for automatic browser page refresh.

> ### About the auto refresher
>
> The `--refresh` flag enables automatic HTML page refresh via the `fastapi-reloader` package. This differs from Uvicorn's built-in `--reload` functionality (see configuration section for details).
>
> Server reloading is a core feature of `uvicorn-hmr` and is always active, regardless of the `--refresh` flag. The `--refresh` flag specifically controls HTML page auto-refresh, a feature not available in standard Uvicorn.
>
> If you don't need HTML page auto-refresh, simply omit the `--refresh` flag. If you do, ensure `fastapi-reloader` is installed via `pip install fastapi-reloader` or `pip install uvicorn-hmr[all]`.

</details>

## Usage

Replace

```sh
uvicorn main:app --reload
```

with

```sh
uvicorn-hmr main:app
```

Everything will work as-expected, but with **hot** module reloading.

## Programmatic Usage

If your application already constructs its own `uvicorn.Config` and `uvicorn.Server`, you can embed `uvicorn-hmr` and keep those pieces under your control by providing an app loader and a server factory.

```python
from pathlib import Path

import uvicorn

from uvicorn_hmr import UvicornHMRConfig, UvicornHMRHooks, run_with_hmr


def load_app():
    # Important: avoid importing your target module before `uvicorn-hmr` starts,
    # otherwise it will be imported as a normal module and won't hot-reload.
    from myapp.entrypoint import build_asgi_app

    return build_asgi_app()


def make_server(app):
    config = uvicorn.Config(app, host="localhost", port=8000, log_level="info")
    return uvicorn.Server(config)


run_with_hmr(
    entry=Path(__file__),
    load_app=load_app,
    make_server=make_server,
    hmr=UvicornHMRConfig(
        reload_include=[str(Path.cwd())],
        reload_exclude=[".venv"],
        extra_watch_files=[Path(".env")],
    ),
    hooks=UvicornHMRHooks(
        # Use these hooks to clean up background threads/tasks and other resources
        # that would otherwise accumulate across reloads.
        before_shutdown=None,
        after_reload=None,
    ),
)
```

Notes:

- If you already have an event loop, use `run_with_hmr_async(...)` instead of `run_with_hmr(...)`.
- The `make_server(app)` callable must return a `uvicorn.Server`-like instance with an async `serve()` method and a `should_exit` flag.
- For slug-based programmatic usage, you can also call `run_slug_with_hmr("module:app", ...)`.

## CLI Arguments

I haven't copied all the configurable options from `uvicorn`. But contributions are welcome!

For now, `host`, `port`, `log-level`, `env-file` are supported and have exactly the same semantics and types as in `uvicorn`.

The behavior of `reload_include` and `reload_exclude` is different from uvicorn in several ways:

1. Uvicorn allows specifying patterns (such as `*.py`), but in uvicorn-hmr only file or directory paths are allowed; patterns will be treated as literal paths.
2. Uvicorn supports watching non-Python files (such as templates), and uvicorn-hmr also supports hot-reloading when any accessed files are modified (including config files, templates, data files, etc.) through reactive file system tracking.
3. Uvicorn always includes/excludes all Python files by default (even if you specify `reload-include` or `reload-exclude`, all Python files are still watched/excluded accordingly), but uvicorn-hmr only includes/excludes the paths you specify. If you do not provide `reload_include`, the current directory is included by default; if you do provide it, only the specified paths are included. The same applies to `reload_exclude`.

The following options are supported but do not have any alternative in `uvicorn`:

- `--refresh`: Enables auto-refreshing of HTML pages in the browser whenever the server restarts. Useful for demo purposes and visual debugging. This is **totally different** from `uvicorn`'s built-in `--reload` option, which is always enabled and can't be disabled in `uvicorn-hmr` because hot-reloading is the core feature of this package.
- `--clear`: Wipes the terminal before each reload. Just like `vite` does by default.
- `--asset-include` / `--asset-exclude`: When used with `--refresh`, changes matching these specs will refresh the browser without restarting the server. Entries can be directory roots (prefix match), files, or globs (matched relative to the current working directory; absolute patterns are also accepted). Excludes win, and `*.py` is always treated as code (never as an asset refresh trigger).
- `--watch-debounce-ms` / `--watch-step-ms`: Override watchfiles batching behavior (defaults come from watchfiles). Useful when restarts are slow and you want to coalesce bursts of edits into fewer reload cycles.
- `--restart-cooldown-ms`: Rate-limit restarts by enforcing a minimum interval between server starts (changes are still applied; restarts are queued until the cooldown expires).

The two features above are opinionated and are disabled by default. They are just my personal practices. If you find them useful or want to suggest some other features, feel free to open an issue.
