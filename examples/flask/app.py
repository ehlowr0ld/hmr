from threading import Thread

from a import a
from b import b
from flask import Flask

app = Flask(__name__)

app.register_blueprint(a)
app.register_blueprint(b)


@app.route("/")
def index():
    return "Hello from main.py!"


class ServerThread(Thread):
    def __init__(self):
        from werkzeug.serving import make_server

        super().__init__(daemon=True)
        self.server = make_server("localhost", 5000, app, threaded=True)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        print("Starting server on http://localhost:5000")
        self.server.serve_forever()

    def shutdown(self):
        print("Shutting down server...")
        self.server.shutdown()


def start_server():
    from atexit import register, unregister

    global server

    if server := globals().get("server"):
        unregister(server.shutdown)
        server.shutdown()

    server = ServerThread()
    server.start()
    register(server.shutdown)


if __name__ == "__main__":
    start_server()
