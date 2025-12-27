# wsgi-hmr

Hot Module Reloading for WSGI development servers (Werkzeug), built on the same HMR runner as `uvicorn-hmr`.

## CLI

```sh
wsgi-hmr module:app
```

Enable browser auto-refresh (requires HTML responses):

```sh
wsgi-hmr module:app --refresh
```

Asset refresh-only (reload browser without restarting the server):

```sh
wsgi-hmr module:app --refresh --asset-include webui --asset-exclude webui/vendor
```

Tune watch batching (useful when restarts are slow and you want to coalesce bursts of edits):

```sh
wsgi-hmr module:app --watch-debounce-ms 2500 --watch-step-ms 100
```

Rate-limit restarts (changes are still applied; restarts are queued until the cooldown expires):

```sh
wsgi-hmr module:app --restart-cooldown-ms 2000
```
