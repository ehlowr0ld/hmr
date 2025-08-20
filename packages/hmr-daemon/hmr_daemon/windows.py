from functools import wraps
from os import getenv
from pathlib import Path
from sys import argv
from threading import Event, Thread, local

from reactivity.hmr import __file__ as hmr_file
from reactivity.hmr.core import BaseReloader, ErrorFilter, ReactiveModuleLoader, SyncReloader, patch_meta_path


def get_code(_: ReactiveModuleLoader, fullname: str):
    from ast import parse
    from importlib.util import find_spec

    if (spec := find_spec(fullname)) is not None and (file := spec.origin) is not None:
        return compile(parse(Path(file).read_text(), str(file)), str(file), "exec", dont_inherit=True)


ReactiveModuleLoader.get_code = get_code  # type: ignore


def patch():
    global original_init

    @wraps(original_init := BaseReloader.__init__)
    def wrapper(*args, **kwargs):
        if not state.disabled:
            shutdown_event.set()
            BaseReloader.__init__ = original_init
        original_init(*args, **kwargs)

    BaseReloader.__init__ = wrapper


def main():
    state.disabled = True

    class Reloader(SyncReloader):
        def __init__(self):
            self.includes = (".",)
            self.excludes = excludes
            self.error_filter = ErrorFilter(*map(str, Path(hmr_file, "..").resolve().glob("**/*.py")), __file__)

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


excludes = (venv,) if (venv := getenv("VIRTUAL_ENV")) else ()

patch_meta_path(excludes=excludes)

shutdown_event = Event()

patch_first = "hmr" in Path(argv[0]).name

(state := local()).disabled = False

if patch_first:
    patch()
    Thread(target=main, daemon=True, name="hmr-daemon").start()
else:
    Thread(target=lambda: [patch(), main()], daemon=True, name="hmr-daemon").start()
