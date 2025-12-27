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
    from tokenize import open as tokenize_open

    if (spec := find_spec(fullname)) is not None and (file := spec.origin) is not None:
        with tokenize_open(file) as f:
            source = f.read()
        return compile(parse(source, str(file)), str(file), "exec", dont_inherit=True)


ReactiveModuleLoader.get_code = get_code  # pyright: ignore[reportAttributeAccessIssue]


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

            debounce_ms: int | None = None
            step_ms: int | None = None
            try:
                if (raw := getenv("HMR_DAEMON_DEBOUNCE_MS")) is not None:
                    debounce_ms = int(raw)
                if (raw := getenv("HMR_DAEMON_STEP_MS")) is not None:
                    step_ms = int(raw)
            except ValueError:
                debounce_ms = None
                step_ms = None

            watch_base_kwargs = {"watch_filter": PythonFilter(), "stop_event": shutdown_event}
            watch_iter = watch(".", **watch_base_kwargs)
            if debounce_ms is not None and debounce_ms >= 0 and step_ms is not None and step_ms >= 1:
                watch_iter = watch(".", debounce=debounce_ms, step=step_ms, **watch_base_kwargs)
            elif debounce_ms is not None and debounce_ms >= 0:
                watch_iter = watch(".", debounce=debounce_ms, **watch_base_kwargs)
            elif step_ms is not None and step_ms >= 1:
                watch_iter = watch(".", step=step_ms, **watch_base_kwargs)

            for events in watch_iter:
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
