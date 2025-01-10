from flask import Blueprint

b = Blueprint("b", __name__, url_prefix="/b")


name = "world"


@b.route("/")
def index():
    print(f"Hello {name}!")
    return f"Hello {name}!"
