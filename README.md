# HMR for Python

[![PyPI - Version](https://img.shields.io/pypi/v/hmr)](https://pypi.org/project/hmr/)
[![PyPI - Downloads](https://img.shields.io/pypi/dw/hmr)](https://pepy.tech/projects/hmr)

HMR means Hot Module Reload / [Hot Module Replacement](https://webpack.js.org/concepts/hot-module-replacement/). It is a feature that allows part of your app to be updated at runtime without a full rerun.

In contrast to the traditional way of reloading Python applications (like [watchfiles CLI](https://watchfiles.helpmanual.io/cli/), [uvicorn --reload](https://www.uvicorn.org/settings/#reloading-with-watchfiles) or [Flask's](https://flask.palletsprojects.com/en/stable/server/) debug mode), HMR is just more efficient.

https://github.com/user-attachments/assets/f9ac6302-44dc-4a6d-86ae-f299fae7be80

Imagine you're developing an ML service using [FastAPI](https://fastapi.tiangolo.com/) with a model that requires 5 seconds to initialize. When using `uvicorn --reload`, any change—even updating a simple docstring—triggers a code restart, forcing you to wait those 5 seconds every time. It's as frustrating as encountering a red light at every intersection.

HMR offers a smoother experience. Changes take effect instantly because HMR intelligently reruns only what's necessary. Your codebase functions like a dependency graph—when you modify a file, HMR only reruns the affected modules from that modified module up to your entry point file, without restarting the whole app.

> [!CAUTION]
>
> ## What this package is not?
>
> `hmr` should not be confused with client-side hot reloading that updates browser content when server code changes. This package implements server-side HMR, which only reloads python code upon changes.

## Usage

```sh
pip install hmr
hmr path/to/your/entry-file.py
```

If you have `uv` installed, you can try `hmr` directly with:

```sh
uvx hmr path/to/your/entry-file.py
```

Please note that hmr is still in early development. While it works well with simple modules, frameworks like ASGI servers or pytest may require specific integration methods.

https://github.com/user-attachments/assets/fb247649-193d-4eed-b778-05b02d47c3f6


## Motivation

HMR is already a common feature in the frontend world. Web frameworks like [Vite](https://vite.dev/) supports syncing changes to the browser without a full refresh. Test frameworks like [Vitest](https://vitest.dev/) supports on-demand updating test results without a full rerun.

So, why not bring this magic to Python?

## How it works

1. [`Signal`](https://docs.solidjs.com/concepts/intro-to-reactivity#signals) is an alternative of the observer pattern. I implemented [a simple signal system](https://github.com/promplate/pyth-on-line/blob/0b14d04e36337a6ff4d5a7a84cd22ee6890901e7/src/python/common/reactivity/primitives.py) to notify changes.
2. I implemented [a custom Module class](https://github.com/promplate/pyth-on-line/blob/0b14d04e36337a6ff4d5a7a84cd22ee6890901e7/src/python/common/reactivity/hmr.py#L44) which tracks every `__getattr__` and `__setattr__` calls. When a key is changed, it will notify the modules who used it. This notification is recursive but fine-grained.
3. `watchfiles` is used to [detect fs changes](https://github.com/promplate/pyth-on-line/blob/0b14d04e36337a6ff4d5a7a84cd22ee6890901e7/src/python/common/reactivity/hmr.py#L177). If a change's path is a python module that has been imported, it will notify the corresponding ones.

## Contributing

This might just be the first fine-grained HMR framework in the Python ecosystem—and honestly, I think the real magic lies in the ecosystem we build around it.

Pair `uvicorn` + `hmr`, and you’ve got yourself a Vite-like development experience. Combine `pytest` + `hmr`, and you’re basically running Vitest for Python. The possibilities with other libraries? Endless. Let’s brainstorm together—who knows what fun (or mildly chaotic) things we might create!

> [!TIP]
> A little backstory: the code for hmr lives in [another repo](https://github.com/promplate/pyth-on-line/tree/reactivity/src/python/common/reactivity) because, truth be told, I wasn’t planning on building an HMR framework. This started as an experiment in bringing reactive programming to Python. Along the way, I realized why not make a module’s globals [reactive](https://github.com/promplate/pyth-on-line/blob/hmr/v0.4.1.1/src/python/common/reactivity/helpers.py#L80)? And that’s how hmr was born! While it began as a side project, I see tremendous potential in it.

For now, this repo is a humble README and a place to kick off the conversation. If you think hmr has potential, or you just want to throw ideas around, I’d love to hear from you. We believe that the Python community can benefit from a more dynamic development experience, and we’re excited to see where this can take us!

## Further reading

About fine-grained reactivity, I recommend reading [SolidJS’s excellent explanation](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity).
