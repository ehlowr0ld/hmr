# Flask Example

This example demonstrates how to use HMR with a Flask application.

## How to Run

After installing dependencies, run the following command in this directory:

```sh
hmr app.py
```

This will start a Flask development server with HOT-reloading enabled.

## What to Observe

Once the server is running, you can access the application at `http://localhost:5000`.

- Visit `http://localhost:5000/a` and `http://localhost:5000/b`.
- Try modifying `b.py` and refresh the browser to see the changes applied instantly (without rerunning `sleep(1)` in `a.py`).
- Everything else should work as expected too. You will find your development experience much smoother than just using `flask dev --reload`.

> [!NOTE]
> Unlike [the FastAPI example](../fastapi/), we haven't implement an integration for Werkzeug, which is the WSGI server used by Flask.
> If you know the `flask` CLI or `werkzeug` well, you are welcome to contribute an integration.
