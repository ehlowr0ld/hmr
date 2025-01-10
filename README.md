# HMR for Python

HMR means Hot Module Reload. It is a feature that allows part of your app to be updated at runtime without a full rerun.

In contrast to the traditional way of reloading Python applications (like watchfiles CLI, uvicorn --reload or Flask's debug mode), HMR is just more efficient.

Imagine you’re building a ML service with FastAPI. Your model takes ~5 seconds to load. Every time you change anything (yes, even something trivial like a docstring of a endpoint handler), `uvicorn --reload` makes you sit through another full 5-second restart. It’s like hitting a traffic light at every block.

With HMR, it’s more like clear roads ahead. Changes are applied instantly. Behind the scenes, HMR works by updating your code on-demand. Picture your codebase as a dependency graph: when you edit a file, HMR only reruns the parts of the graph affected by that change—from the deepest dependency all the way up to your entry file—without restarting the whole app.

With HMR, you can see the changes immediately. Under the hood, code reruns on-demand. Imagine a dependency graph of your code. When you change a file, HMR will rerun the affected parts of the graph, from deep to shallow, until the entry file is reached.

https://github.com/user-attachments/assets/f9ac6302-44dc-4a6d-86ae-f299fae7be80

## Usage

```sh
pip install hmr
hmr path/to/your/entry-file.py
```

If you have `uv` installed, you can try `hmr` directly with:

```sh
uvx hmr path/to/your/entry-file.py
```

Note that hmr is not well-tested yet. Simple modules should work fine, but frameworks like ASGI servers or pytest may work better with especial integration.

https://github.com/user-attachments/assets/fb247649-193d-4eed-b778-05b02d47c3f6

## Motivation

HMR is already a common feature in the frontend world. Web frameworks like Vite supports syncing changes to the browser without a full refresh. Test frameworks like Vitest supports on-demand updating test results without a full rerun.

So, why not bring this magic to Python?

## How it works

1. `Signal` is an alternative of the observer pattern. I implemented a simple signal system to notify changes.
2. I implemented a custom Module class which tracks every `__getattr__` and `__setattr__` calls. When a key is changed, it will notify the modules who used it. This notification is recursive but fine-grained.
3. `watchfiles` is used to detect fs changes. If a change's path is a python module that has been imported, it will notify the corresponding ones.

## Contributing

This might just be the first fine-grained HMR (Hot Module Replacement) framework in the Python ecosystem—and honestly, I think the real magic lies in the ecosystem we build around it.

Pair `uvicorn` + `hmr`, and you’ve got yourself a Vite-like development experience. Combine `pytest` + `hmr`, and you’re basically running Vitest for Python. The possibilities with other libraries? Endless. Let’s brainstorm together—who knows what fun (or mildly chaotic) things we might create!

> [!TIP]
> A little backstory: the code for hmr lives in another repo because, truth be told, I wasn’t planning on building an HMR framework. This started as an experiment in bringing reactive programming to Python. Along the way, I realized why not make a module’s globals reactive? And that’s how hmr was born! While it began as a side project, I see tremendous potential in it.

For now, this repo is a humble README and a place to kick off the conversation. If you think hmr has potential, or you just want to throw ideas around, I’d love to hear from you. We believe that the Python community can benefit from a more dynamic development experience, and we’re excited to see where this can take us!`
