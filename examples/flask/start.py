"""
You don't need to understand what this code does.

This file implements a simple function to start a Flask server like `flask run --reload`.

To use it, just copy this file to your project and call the `start_server` function with your Flask app instance.
And then run this file with `hmr path/to/this/file.py`.

We haven't implement a separate integration for Werkzeug, which is the WSGI server used by Flask.
So you need to use this function to start the server with HMR support.
"""

from atexit import register, unregister
from threading import Thread
from typing import cast

from flask import Flask


class ServerThread(Thread):
    def __init__(self, app: Flask):
        super().__init__(daemon=True)
        self.app = app

    def run(self):
        from werkzeug.serving import make_server

        self.server = make_server("localhost", 5000, self.app, threaded=True)
        self.server.serve_forever(poll_interval=0.1)

    def shutdown(self):
        self.server.shutdown()


def start_server(app: Flask):
    global server

    print("* Running on http://localhost:5000")

    if server := cast("ServerThread | None", globals().get("server")):
        unregister(server.shutdown)
        server.shutdown()

    server = ServerThread(app)
    server.start()
    register(server.shutdown)


if __name__ == "__main__":
    from app import app

    start_server(app)
