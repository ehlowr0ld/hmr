# hmr-runner

`hmr-runner` contains the shared hot-reload orchestration used by `uvicorn-hmr` and `wsgi-hmr`.

It is not intended to be used directly unless you are building a custom runner.

## Watch Batching Knobs

The runner uses `watchfiles` to collect filesystem events. If your server restarts are slow, you can tune these optional fields on `hmr_runner.HMRConfig`:

- `watch_debounce_ms`: Passed through to `watchfiles.awatch(..., debounce=...)` when set
- `watch_step_ms`: Passed through to `watchfiles.awatch(..., step=...)` when set
- `restart_cooldown_ms`: Rate-limit server restarts by enforcing a minimum interval between server starts (changes are still applied; restarts are queued until the cooldown expires)
