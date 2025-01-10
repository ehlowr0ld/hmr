import a
import b
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

app = FastAPI()

app.include_router(a.router)
app.include_router(b.router)


@app.get("/")
def redirect_to_docs():
    return RedirectResponse("/docs")


def start_server():
    global stop

    from atexit import register, unregister
    from threading import Event, Thread

    from uvicorn import Config, Server

    if stop := globals().get("stop"):  # type: ignore
        unregister(stop)
        stop()  # type: ignore

    server = Server(Config(app, host="localhost"))

    finish = Event()

    def run_server():
        server.run()
        finish.set()

    Thread(target=run_server, daemon=True).start()

    @register
    def stop():
        server.should_exit = True
        finish.wait()


if __name__ == "__main__":
    start_server()
