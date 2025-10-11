from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from copy import copy
from math import inf
from typing import TypeGuard

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


async def _injection_http_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    res = await call_next(request)

    if request.method != "GET" or "html" not in (res.headers.get("content-type", "")) or res.headers.get("content-encoding", "identity") != "identity":
        return res

    async def response():
        if is_streaming_response(res):
            async for chunk in res.body_iterator:
                yield chunk
        else:
            yield res.body

        yield b'\n\n <script src="/---fastapi-reloader---/poller.js"></script>'

    headers = {k: v for k, v in res.headers.items() if k.lower() not in {"content-length", "transfer-encoding"}}

    return StreamingResponse(response(), res.status_code, headers, res.media_type)


injection_middleware = Middleware(BaseHTTPMiddleware, dispatch=_injection_http_middleware)


def _reloader_middleware(app: ASGIApp):
    @asynccontextmanager
    async def lifespan(_):
        async with LifespanManager(app, inf, inf):
            yield

    new_app = FastAPI(openapi_url=None, lifespan=lifespan)
    new_app.include_router(reload_router)
    new_app.mount("/", app)

    return new_app


def patch_for_auto_reloading(app: ASGIApp):
    if isinstance(app, Starlette):  # both FastAPI and Starlette have user_middleware attribute
        new_app = copy(app)
        new_app.user_middleware = [*app.user_middleware, injection_middleware]  # before compression middlewares
        return _reloader_middleware(new_app)

    new_app = _reloader_middleware(app)
    new_app.user_middleware.append(injection_middleware)  # the last middleware is the first one to be called

    return new_app
