from common import console


def f():
    console.print("[red] hello from b.py")


def g():
    f()
    return 2


b = g()
