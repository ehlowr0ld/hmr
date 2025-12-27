from json import dumps
from os import getenv
from signal import SIG_IGN, SIGINT, SIGTERM, signal
from threading import Event

from watchfiles import PythonFilter, watch

signal(SIGINT, SIG_IGN)

signal(SIGTERM, lambda *_: shutdown_event.set())

shutdown_event = Event()

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
    try:
        # Serialize entire events set as JSON
        events_data = [(int(event), path) for event, path in events]
        print(dumps(events_data))
    except (OSError, BrokenPipeError):
        exit()  # Parent process disconnected
