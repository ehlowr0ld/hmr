from time import sleep

from flask import Blueprint

a = Blueprint("a", __name__, url_prefix="/a")


sleep(1)
print("slow module a.py imported")


@a.route("/")
def index():
    return "Hello from a.py!"
