# uvicorn-hmr

This package provides hot module reloading (HMR) for [`uvicorn`](https://github.com/encode/uvicorn).

It uses [`watchfiles`](https://github.com/samuelcolvin/watchfiles) to detect FS modifications,
re-executes the corresponding modules and restart the server (in the same process).

Since the reload is on-demand and the server is not restarted on every request, it is much faster than the built-in `--reload` option provided by `uvicorn`.

## Installation

```sh
pip install uvicorn-hmr
```

## Usage

Replace

```sh
uvicorn main:app --reload
```

with

```sh
uvicorn-hmr main:app
```

> [!NOTE]
> Since this package is a proof-of-concept yet, there is no configuration available. But contributions are welcome!

## Why?

1. Restarting process on every request is not always necessary, and is rather expensive. With `hmr`, 3-party packages imports are memoized.
2. `hmr` track dependencies on runtime, and only rerun necessary modules. If you changed a python file not used by the server entrypoint, it won't be reloaded.

## What this package is not?

> [!CAUTION]
> `hmr` are sometimes refer to a feature that updates the page in the browser on the client side when the server code changes. This is not that. This package is a server-side HMR, that reloads the server code when it changes.
