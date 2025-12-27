from __future__ import annotations

from queue import Empty
from typing import TYPE_CHECKING

from ._hub import hub
from ._runtime import INJECTION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from types import TracebackType

    type Environ = dict[str, object]
    type StartResponse = Callable[[str, list[tuple[str, str]], TracebackType | None], Callable[[bytes], object]]
    type WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]


RELOADER_PATH = "/---fastapi-reloader---"
_FLAG = "hmr-reloader-injected"


def wsgi_reloader_endpoint(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    if method == "HEAD":
        start_response("202 Accepted", [], None)
        return []

    if method != "GET":
        start_response("405 Method Not Allowed", [("content-type", "text/plain")], None)
        return [b"Method not allowed"]

    start_response("201 Created", [("content-type", "text/plain")], None)

    def body() -> Iterator[bytes]:
        with hub.subscription() as q:
            yield b"0\n"
            while True:
                try:
                    value = q.get(timeout=1)
                except Empty:
                    yield b"0\n"
                    continue
                yield f"{value}\n".encode()
                if value == 1:
                    break

    return body()


def wsgi_reloader_route_middleware(app: WSGIApp) -> WSGIApp:
    def middleware(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO", ""))
        if path.rstrip("/") == RELOADER_PATH:
            return wsgi_reloader_endpoint(environ, start_response)
        return app(environ, start_response)

    return middleware


def _get_header(headers: list[tuple[str, str]], name: str) -> str | None:
    name = name.lower()
    for k, v in headers:
        if k.lower() == name:
            return v
    return None


def wsgi_html_injection_middleware(app: WSGIApp) -> WSGIApp:
    def middleware(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        if environ.get(_FLAG):
            return app(environ, start_response)

        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", ""))
        if method != "GET" or path.rstrip("/") == RELOADER_PATH:
            return app(environ, start_response)

        status_line: str | None = None
        response_headers: list[tuple[str, str]] | None = None
        exc: TracebackType | None = None
        body_prefix: list[bytes] = []

        def sr(status: str, headers: list[tuple[str, str]], exc_info: TracebackType | None = None):
            nonlocal status_line, response_headers, exc
            status_line = status
            response_headers = list(headers)
            exc = exc_info

            def write(data: bytes):
                body_prefix.append(data)
                return None

            return write

        result = app(environ, sr)

        if status_line is None or response_headers is None:
            return result

        content_type = (_get_header(response_headers, "content-type") or "").lower()
        content_encoding = (_get_header(response_headers, "content-encoding") or "identity").lower()
        should_inject = ("html" in content_type) and content_encoding == "identity"

        if not should_inject:
            start_response(status_line, response_headers, exc)
            return result

        environ[_FLAG] = True
        filtered_headers = [(k, v) for (k, v) in response_headers if k.lower() not in {"content-length", "transfer-encoding"}]
        start_response(status_line, filtered_headers, exc)

        def response() -> Iterator[bytes]:
            try:
                yield from body_prefix
                yield from result
                yield INJECTION
            finally:
                close = getattr(result, "close", None)
                if close is not None:
                    close()

        return response()

    return middleware


def wsgi_auto_refresh_middleware(app: WSGIApp) -> WSGIApp:
    return wsgi_html_injection_middleware(wsgi_reloader_route_middleware(app))
