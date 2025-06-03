from asyncio import Queue, ensure_future, sleep
from collections import defaultdict
from itertools import count
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

get_id = count().__next__

requests: dict[int, list[Queue[Literal[0, 1]]]] = defaultdict(list)


def send_reload_signal():
    for subscribers in requests.values():
        for queue in subscribers:
            queue.put_nowait(1)


reload_router = APIRouter(prefix="/---fastapi-reloader---", tags=["hmr"])


runtime_js = Path(__file__, "../runtime.js").read_text()


def get_js():
    return runtime_js.replace("/0", f"/{get_id()}")


@reload_router.head("")
async def heartbeat():
    return Response(status_code=200)


@reload_router.get("/{key:int}")
async def simple_refresh_trigger(key: int):
    async def event_generator():
        queue = Queue[Literal[0, 1]]()

        stopped = False

        async def heartbeat():
            while not stopped:
                queue.put_nowait(0)
                await sleep(1)

        requests[key].append(queue)

        heartbeat_future = ensure_future(heartbeat())

        try:
            yield "0\n"
            while True:
                value = await queue.get()
                yield f"{value}\n"
                if value == 1:
                    break
        finally:
            heartbeat_future.cancel()
            requests[key].remove(queue)

    return StreamingResponse(event_generator(), media_type="text/plain")
