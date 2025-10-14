from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from copy import copy
from inspect import ismethod
from math import inf
from pathlib import Path
from types import MethodType
from typing import Generic, TypeGuard, TypeVar

from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .core import reload_router


def is_streaming_response(response: Response) -> TypeGuard[StreamingResponse]:
    # In fact, it may not be a Starlette's StreamingResponse, but an internal one with the same interface
    return hasattr(response, "body_iterator")


INJECTION = f"\n\n<script>\n{Path(__file__, '../runtime.js').resolve().read_text()}\n</script>".encode()

FLAG = " fastapi-reloader-injected "  # to avoid double injection


async def _injection_http_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    res = await call_next(request)

    if request.scope.get(FLAG) or request.method != "GET" or "html" not in (res.headers.get("content-type", "")) or res.headers.get("content-encoding", "identity") != "identity":
        return res

    request.scope[FLAG] = True

    async def response():
        if is_streaming_response(res):
            async for chunk in res.body_iterator:
                yield chunk
        else:
            yield res.body

        yield INJECTION

    headers = {k: v for k, v in res.headers.items() if k.lower() not in {"content-length", "transfer-encoding"}}

    return StreamingResponse(response(), res.status_code, headers, res.media_type)


T = TypeVar("T", bound=ASGIApp)


class UniversalMiddleware(Middleware, Generic[T]):  # noqa: UP046
    """Adapt an ASGI middleware so it can serve both Starlette/FastAPI middleware slots and plain ASGI usage."""

    def __init__(self, asgi_middleware: Callable[[ASGIApp], T]):
        self.fn = asgi_middleware
        super().__init__(self)

    def __call__(self, app):
        return self.fn(app)


html_injection_middleware = UniversalMiddleware(lambda app: BaseHTTPMiddleware(app, _injection_http_middleware))
"""This middleware injects the HMR client script into HTML responses."""


def _wrap_asgi_app(app: ASGIApp):
    @asynccontextmanager
    async def lifespan(_):
        async with LifespanManager(app, inf, inf):
            yield

    new_app = FastAPI(openapi_url=None, lifespan=lifespan)
    new_app.include_router(reload_router)
    new_app.mount("/", app)

    return new_app


reloader_route_middleware = UniversalMiddleware(_wrap_asgi_app)
"""This middleware wraps the app with a FastAPI app that handles reload signals."""


def patch_for_auto_reloading(app: ASGIApp):  # this function is preserved for backward compatibility
    if isinstance(app, Starlette):  # both FastAPI and Starlette have user_middleware attribute
        new_app = copy(app)
        new_app.user_middleware = [*app.user_middleware, html_injection_middleware]  # before compression middlewares

        # OTEL patches the app's build_middleware_stack method and keep a reference to the original build_middleware_stack.
        # But both methods are bound to the original app instance, so we need to rebind them to the new app instance.
        # The following loop generically rebinds all these methods, preventing potential issues caused by similar patches.
        for i in dir(new_app):
            if ismethod(method := getattr(new_app, i)) and method.__self__ is app:
                setattr(new_app, i, MethodType(method.__func__, new_app))

        return _wrap_asgi_app(new_app)

    new_app = _wrap_asgi_app(app)
    new_app.user_middleware.append(html_injection_middleware)  # the last middleware is the first one to be called

    return new_app


auto_refresh_middleware = UniversalMiddleware(patch_for_auto_reloading)
"""This middleware combines the two middlewares above to enable the full functionality of this package."""
