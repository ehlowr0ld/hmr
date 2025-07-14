from a import a
from b import b
from flask import Flask

app = Flask(__name__)

app.register_blueprint(a)
app.register_blueprint(b)


@app.route("/")
def index():
    return "Hello from main.py!"


def start_server():
    """
    This is the entry function to replace the default `flask run --reload` command.
    You don't need to understand this function in detail.
    We haven't implement a separate integration for Werkzeug, which is the WSGI server used by Flask.
    So you need to use this function to start the server with HMR support.
    """
    from atexit import register, unregister
    from threading import Thread
    from typing import cast

    global ServerThread, server

    if "server" not in globals():

        class ServerThread(Thread):
            def run(self):
                print("* Running on http://localhost:5000")

                from werkzeug.serving import make_server

                self.server = make_server("localhost", 5000, app, threaded=True)
                self.server.serve_forever(poll_interval=0.1)

            def shutdown(self):
                self.server.shutdown()

    if server := cast("ServerThread | None", globals().get("server")):
        unregister(server.shutdown)
        server.shutdown()

    server = ServerThread(daemon=True)
    server.start()
    register(server.shutdown)


if __name__ == "__main__":
    start_server()
