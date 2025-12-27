from atexit import register
from os import environ
from subprocess import PIPE, Popen, TimeoutExpired
from sys import executable

from .main import run_reloader

env = dict(environ)
env["NO_HMR_DAEMON"] = "1"
run_reloader(worker := Popen([executable, "-u", __file__.replace("__init__", "worker")], stdout=PIPE, env=env))


@register
def _():
    worker.terminate()
    try:
        worker.wait(timeout=0.1)
    except TimeoutExpired:
        worker.kill()
