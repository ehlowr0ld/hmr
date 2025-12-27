from __future__ import annotations

from contextlib import contextmanager
from itertools import count
from queue import Queue
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class _ReloadHub:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = count().__next__
        self._subscribers: dict[int, Queue[int]] = {}

    @contextmanager
    def subscription(self) -> Iterator[Queue[int]]:
        key = self._next_id()
        q: Queue[int] = Queue()
        with self._lock:
            self._subscribers[key] = q
        try:
            yield q
        finally:
            with self._lock:
                if self._subscribers.get(key) is q:
                    self._subscribers.pop(key, None)

    def broadcast(self, value: int) -> None:
        with self._lock:
            queues = list(self._subscribers.values())
        for q in queues:
            q.put_nowait(value)


hub = _ReloadHub()


def send_reload_signal() -> None:
    hub.broadcast(1)


@contextmanager
def subscription() -> Iterator[Queue[int]]:
    with hub.subscription() as q:
        yield q
