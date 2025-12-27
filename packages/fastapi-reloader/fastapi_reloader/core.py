from asyncio import to_thread
from queue import Empty

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from hmr_reloader import send_reload_signal, subscription

reload_router = APIRouter(prefix="/---fastapi-reloader---", tags=["hmr"])
__all__ = ["reload_router", "send_reload_signal"]


@reload_router.head("")
async def heartbeat():
    return Response(status_code=202)


@reload_router.get("")
async def subscribe():
    async def event_generator():
        with subscription() as q:
            yield "0\n"
            while True:
                try:
                    value = await to_thread(q.get, timeout=1)
                except Empty:
                    yield "0\n"
                    continue
                yield f"{value}\n"
                if value == 1:
                    break

    return StreamingResponse(event_generator(), 201, media_type="text/plain")
