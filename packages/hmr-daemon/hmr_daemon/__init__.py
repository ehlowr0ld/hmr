import os

if "NO_HMR_DAEMON" not in os.environ:
    from threading import enumerate

    if any(t.name == "hmr-daemon" for t in enumerate()):
        if os.name == "nt":
            from . import windows  # noqa: F401
        else:
            from . import posix  # noqa: F401
