from os import getenv
from pathlib import Path
from sys import argv
from threading import Event, Thread, local
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reactivity.hmr.core import BaseReloader

    original_init = BaseReloader.__init__
else:
    original_init = None


def patch():
    global original_init

    from functools import wraps

    from reactivity.hmr.core import BaseReloader

    @wraps(original_init := BaseReloader.__init__)
    def wrapper(*args, **kwargs):
        if not state.disabled:
            shutdown_event.set()
            BaseReloader.__init__ = original_init
        original_init(*args, **kwargs)

    BaseReloader.__init__ = wrapper


def main():
    from reactivity.hmr.core import SyncReloader

    state.disabled = True

    class Reloader(SyncReloader):
        def __init__(self):
            super().__init__("", excludes=(venv,) if (venv := getenv("VIRTUAL_ENV")) else ())
            self.error_filter.exclude_filenames.add(__file__)

        def start_watching(self):
            if shutdown_event.is_set():
                return

            from watchfiles import PythonFilter, watch

            if shutdown_event.is_set():
                return

            for events in watch(".", watch_filter=PythonFilter(), stop_event=shutdown_event):
                self.on_events(events)

    if not shutdown_event.is_set():
        Reloader().start_watching()


shutdown_event = Event()

patch_first = "hmr" in Path(argv[0]).name

(state := local()).disabled = False

if patch_first:
    patch()
    Thread(target=main, daemon=True, name="hmr-daemon").start()
else:
    Thread(target=lambda: [patch(), main()], daemon=True, name="hmr-daemon").start()
