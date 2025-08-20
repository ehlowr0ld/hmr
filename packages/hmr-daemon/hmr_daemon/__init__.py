import os

if "NO_HMR_DAEMON" not in os.environ:
    if os.name == "nt":
        from . import windows  # noqa: F401
    else:
        from . import posix  # noqa: F401
