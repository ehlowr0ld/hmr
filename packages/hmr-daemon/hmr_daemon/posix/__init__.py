from atexit import register
from subprocess import PIPE, Popen, TimeoutExpired
from sys import executable

from .main import run_reloader

run_reloader(worker := Popen([executable, __file__.replace("__init__", "worker")], stdout=PIPE, env={"NO_HMR_DAEMON": "1"}))


@register
def _():
    worker.terminate()
    try:
        worker.wait(timeout=0.1)
    except TimeoutExpired:
        worker.kill()
