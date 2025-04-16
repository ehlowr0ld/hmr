# FastAPI Reloader

[![PyPI - Version](https://img.shields.io/pypi/v/fastapi-reloader)](https://pypi.org/project/fastapi-reloader/)
[![PyPI - Downloads](https://img.shields.io/pypi/dw/fastapi-reloader)](https://pepy.tech/projects/fastapi-reloader/)

A lightweight middleware ASGI applications that enables automatic browser page reloading during development.

## Features

- 🔄 Automatic browser refresh when code changes (work with `uvicorn-hmr`)
- 🚀 Works with any ASGI application
- 🔌 Simple integration with just two function calls

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
uvicorn-hmr main:app --reload
```

## Advanced Usage

### Manual Integration

```python
from fastapi import FastAPI
from fastapi_reloader import patch_for_auto_reloading

app = FastAPI()  # or some other ASGI app

app = patch_for_auto_reloading(app)  # this will return a new FastAPI app
```

### Manual Trigger

You can manually trigger a reload from your code:

```python
from fastapi_reloader import send_reload_signal

send_reload_signal()  # When you need to trigger a reload
```

## How It Works

The package injects a small JavaScript snippet into your HTML responses that:

1. Opens a long-lived connection to the server
2. Listens for reload signals
3. Start polling for heartbeat when `send_reload_signal` is called
4. Reloads the page when heartbeat from new server is received

## Configuration

The package works out-of-the-box with default settings. No additional configuration is required.

## Limitations

- Unlike `uvicorn-hmr`, which does on-demand fine-grained reloading on the server side, this package simply reloads all the pages in the browser.
- Designed for development use only (not for production)
- Requires JavaScript to be enabled in the browser

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
