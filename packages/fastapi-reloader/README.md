# FastAPI Reloader

[![PyPI - Version](https://img.shields.io/pypi/v/fastapi-reloader)](https://pypi.org/project/fastapi-reloader/)
[![PyPI - Downloads](https://img.shields.io/pypi/dw/fastapi-reloader)](https://pepy.tech/projects/fastapi-reloader/)

A lightweight middleware ASGI applications that enables automatic browser page reloading during development.

## Features

- 🔄 Automatic browser refresh when server restarts
- 🚀 Works with any ASGI application and any event loop
- 🔌 Simple integration with just two steps

## Installation

```sh
pip install fastapi-reloader
```

For a more comprehensive development experience, consider using `uvicorn-hmr` which includes this package:

```sh
pip install uvicorn-hmr[all]
```

Then run your app with:

```sh
uvicorn-hmr main:app --refresh
```

## Standalone Usage

You can also use `fastapi-reloader` as a standalone package without `uvicorn-hmr`. However, there are a few things to keep in mind.

It's important to understand the roles of the different packages:

- `uvicorn-hmr` Provides server-side hot module reloading (as a drop-in replacement for `uvicorn --reload`).
- `fastapi-reloader` Triggers a [browser page refresh](https://developer.mozilla.org/docs/Web/API/Location/reload "window.reload") when the server restarts.

If you configure `fastapi-reloader` manually and run your ASGI app with a standard reloader like `uvicorn --reload`, the behavior will be similar to `uvicorn-hmr --refresh` but with "cold" (process-restarting) server reloads instead of "hot" (in-process) reloads provided by [`hmr`](https://pyth-on-line.promplate.dev/hmr).

The manual integration steps are quite straightforward:

### Step 1: Add Middleware

`fastapi-reloader` works by injecting a `<script>` tag into HTML responses.

```python
from fastapi import FastAPI
from fastapi_reloader import auto_refresh_middleware

app = FastAPI()
app.add_middleware(auto_refresh_middleware)
```

Note that this middleware must be placed **before** any compression middleware (like Starlette's `GZipMiddleware`).

If you can't place it as early as possible in the middleware stack, you can use the following ways:

```python
# Approach 1: wrap your app with it (works with any ASGI app)
app = html_injection_middleware(app)

# Approach 2: manually add it to the user_middleware list (supported FastAPI, Starlette etc.)
app.user_middleware.append(html_injection_middleware)
```

> It's safe to add `html_injection_middleware` in multiple places, even if their scopes overlap. We have safeguards in place to prevent double injection on both server and client side.

The `auto_refresh_middleware` is a convenient wrapper that applies both `reloader_route_middleware` and `html_injection_middleware`. However, you can add them separately for more control:

- **Fine-grained control**: If a sub-router in your application uses compression, you must add `html_injection_middleware` before the compression middleware on that router.
- **Scoped reloading**: If you only want to enable auto-reloading for a specific part of your app, you can apply `html_injection_middleware` only to that sub-router.

> The `reloader_route_middleware` mounts the necessary endpoints and should typically be added to the main application instance.

```python
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware
from fastapi_reloader import html_injection_middleware, reloader_route_middleware

app = FastAPI()
# Apply the reloader routes to the main app
app.add_middleware(reloader_route_middleware)

# Apply HTML injection middleware before compression ones
app.add_middleware(html_injection_middleware)
app.add_middleware(GZipMiddleware)  # or BrotliMiddleware, ZstMiddleware, etc.
```

FastAPI routers needs further configuration like this (because [`fastapi.APIRouter`](https://fastapi.tiangolo.com/reference/apirouter/) doesn't support middlewares directly):

```python
app.mount(router.prefix, html_injection_middleware(router))  # place this first to shadows the next line
app.include_router(router)  # this can't be removed because FastAPI needs it to generate OpenAPI schema
```

### Step 2: Manually Triggering Reloads

When used standalone, you **have to** add a few lines into your code to manually *trigger the reload signal* (aka. call `send_reload_signal()`) before your ASGI server shuts down (I mean, when a server receives a shutdown signal like SIGINT/SIGTERM or it want to restart because of code changes etc.). `fastapi-reloader` works with any ASGI server, but most of them wait for open connections to close before shutting down. The long-polling connection internally used by `uvicorn-hmr` won't close on its own (because we have no idea of when it will happen), preventing the server from shutting down gracefully (behaving like a deadlock).

So you need to hook into your ASGI server's shutdown process to call `send_reload_signal()`. This can be done through subclassing, monkey-patching, or using a library like [`dowhen`](https://github.com/gaogaotiantian/dowhen).

Here is an example for `uvicorn`:

```python
from fastapi_reloader import send_reload_signal
import uvicorn

_shutdown = uvicorn.Server.shutdown

def shutdown(self, *args, **kwargs):
    send_reload_signal()
    return _shutdown(self, *args, **kwargs)

uvicorn.Server.shutdown = shutdown
```

and start the server as normal

```sh
uvicorn main:app --reload
```

or this way:

```python
if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)
```

## How It Works

The package injects a small JavaScript snippet into your HTML responses that:

1. Opens a long-lived connection to the server
2. Listens for reload signals
3. Starts polling for heartbeat when `send_reload_signal` is called
4. Reloads the page when heartbeat from new server is received

## Configuration

The package works out-of-the-box with default settings. No additional configuration is required.

## Limitations

- Unlike `uvicorn-hmr`, which does on-demand fine-grained reloading on the server side, this package simply reloads all the pages in the browser.
- Designed for development use only (not for production)
- Requires JavaScript to be enabled in the browser

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
