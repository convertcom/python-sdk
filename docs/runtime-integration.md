# Runtime Integration Guide

Conversion tracking in the Convert Python SDK is **batched** and delivered when
the in-process queue is **released** (flushed). Choosing *when* to flush is the
single most important runtime decision, because it determines whether queued
events are delivered before your process exits.

This guide gives a copy-pasteable flush strategy for each common Python runtime.

## The model in one paragraph

`context.track_conversion(...)` is lightweight and synchronous — it deduplicates
by `(visitor_id, goal_id)` and appends the event to an in-process queue. **No
network call happens on `track_conversion`.** The queue is released (serialized
and delivered over HTTPS) when one of these happens:

1. **Explicit flush** — you call `core.flush()` (the canonical, deterministic
   control point).
2. **Batch-size release** — the queue reaches `SDKConfig.batch_size` (default
   `10`) and auto-releases.
3. **Periodic flush** — *opt-in only*: set `SDKConfig.auto_flush_interval_ms` to
   start a daemonic background timer.
4. **`atexit`** — *opt-in, best-effort*: `register_atexit_flush(core)` attempts a
   final flush on normal interpreter shutdown.

> The default lifecycle is **explicit-flush-only**, which is safe in every
> runtime. Periodic flush is never the default because a timed flush silently
> loses events in short-lived runtimes (Lambda, CLI scripts) that exit before
> the timer fires.

## Quick decision table

| Runtime | Recommended strategy | Why |
|---------|---------------------|-----|
| AWS Lambda | **Explicit `core.flush()`** at the end of the handler | Frozen/killed between invocations; background timers don't fire reliably. |
| Google Cloud Run | Explicit flush per request **+ optional SIGTERM flush** | Request-scoped; SIGTERM precedes container shutdown. |
| gunicorn (sync workers) | **Periodic flush** (`auto_flush_interval_ms`) **or** per-request flush | Long-lived workers; a daemonic timer amortizes delivery. |
| uvicorn / hypercorn (ASGI) | Periodic flush **or** flush in a shutdown lifespan handler | Long-lived event loop; lifespan shutdown is a clean flush point. |
| Celery workers | Flush at task end **or** periodic flush | Long-lived; per-task flush bounds latency of delivery. |
| CLI / batch scripts | **Explicit `core.flush()`** before exit (and/or `atexit`) | Short-lived; the process exits as soon as work is done. |

## AWS Lambda

Flush explicitly at the end of every handler invocation. Do **not** rely on a
periodic timer or `atexit` — the execution environment is frozen between
invocations and may be killed without firing them.

```python
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()

def handler(event, context):
    ctx = core.create_context(event["visitor_id"])
    ctx.track_conversion("purchase_completed", revenue=event["amount"])
    # Deliver before the runtime freezes/kills the environment.
    core.flush()
    return {"statusCode": 200}
```

## Google Cloud Run

Flush per request. Optionally add a SIGTERM handler for a best-effort final
flush when the container is scaled down (Cloud Run sends SIGTERM before
shutdown). The SDK never registers a signal handler for you — opt in explicitly:

```python
import signal
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()

def _handle_sigterm(signum, frame):
    core.flush()          # best-effort final delivery
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)

@app.post("/checkout")
def checkout(req):
    ctx = core.create_context(req.visitor_id)
    ctx.track_conversion("purchase_completed", revenue=req.amount)
    core.flush()
    return "ok"
```

## gunicorn (sync workers)

Workers are long-lived, so an opt-in daemonic periodic flush amortizes delivery
without an explicit call on every request. The timer thread is daemonic and
never blocks worker shutdown.

```python
from convert_sdk import Core, SDKConfig

# Flush the queue every 5 seconds in the background.
core = Core(
    SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"], auto_flush_interval_ms=5000)
).initialize()
```

Prefer a per-request `core.flush()` instead if you need delivery to be
deterministic per response. Either way, call `core.close()` on worker shutdown
to cancel the timer cleanly.

## uvicorn / hypercorn (ASGI)

Use periodic flush, or flush in the ASGI lifespan shutdown handler for a clean
final delivery:

```python
from contextlib import asynccontextmanager
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()

@asynccontextmanager
async def lifespan(app):
    yield
    core.flush()   # final flush on app shutdown
    core.close()
```

## Celery workers

Long-lived workers: flush at the end of each task (bounded delivery latency) or
enable periodic flush. Per-task flush:

```python
@app.task
def record_purchase(visitor_id, amount):
    ctx = core.create_context(visitor_id)
    ctx.track_conversion("purchase_completed", revenue=amount)
    core.flush()
```

## CLI scripts and batch jobs

Short-lived: flush explicitly before the process exits. Optionally also register
the best-effort `atexit` hook as a safety net (it does not fire under SIGKILL or
hard crashes):

```python
from convert_sdk import Core, SDKConfig
from convert_sdk.tracking.flush import register_atexit_flush

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()
register_atexit_flush(core)   # best-effort final flush on normal exit

ctx = core.create_context("cli-user")
ctx.track_conversion("report_generated")
core.flush()   # explicit, deterministic delivery
```

## What happens if I never flush?

A never-flushed process exits cleanly and **silently drops** its queued events —
no crash, no error (NFR18). This is intentional: tracking must never destabilize
your application. If delivery matters, pick a flush strategy from the table
above.

## Notes on the periodic timer and `atexit`

- The periodic timer uses a **daemonic** `threading.Timer`. Daemonic timers do
  not prevent interpreter shutdown, so if the process exits before the timer
  fires, that flush is silently skipped — the correct behavior for Lambda /
  Cloud Run / CLI runtimes where a non-daemonic background thread would hang the
  process on exit.
- `atexit` is **best-effort**. It does not fire under `SIGKILL`, some serverless
  runtimes, or hard crashes. Never rely on it as your only delivery path.
- All release triggers (batch-size, explicit, timer, `atexit`) funnel through a
  single shared release path, so the serialized payload is identical regardless
  of how the flush was triggered.
