# hmr-reloader

`hmr-reloader` provides a small, shared browser-reload signaling mechanism plus WSGI helpers to inject the client runtime and serve the reload endpoint.

This package is stdlib-only and is intended to be used by:

- `fastapi-reloader` (ASGI wrapper)
- `wsgi-hmr` (Werkzeug dev server runner)


