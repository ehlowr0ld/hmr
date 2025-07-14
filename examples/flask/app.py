from a import a
from b import b
from flask import Flask

app = Flask(__name__)

app.register_blueprint(a)
app.register_blueprint(b)


@app.route("/")
def index():
    return "Hello from main.py!"


if __name__ == "__main__":
    from start import start_server

    start_server(app)
