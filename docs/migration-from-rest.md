# Migrating from raw REST

If you integrate with Convert today by calling the HTTP endpoints directly —
fetching the config payload and POSTing tracking events — the Python SDK gives
you the same outcomes behind a typed, higher-level surface, plus operational
behavior you would otherwise hand-roll. This guide maps your raw REST flows onto
the SDK and shows what you stop having to maintain.

## The two raw REST flows, mapped

| Raw REST today | SDK equivalent |
|----------------|----------------|
| `GET` the config payload for your `sdk_key` over HTTPS | `Core(SDKConfig(sdk_key=...)).initialize()` — fetches and snapshots config once |
| Parse config and run your own bucketing/feature logic | `context.run_experience(key)` / `context.run_feature(key)` — typed results |
| `POST` a tracking event to the tracking endpoint per conversion | `context.track_conversion(goal_key, ...)` then a queue release |

The SDK fetches config exactly like your REST call does, but it then holds an
**immutable config snapshot** and evaluates locally — no per-evaluation network
call.

### Config retrieval: before and after

Raw REST (illustrative):

```python
import os, httpx

resp = httpx.get(
    f"https://config.example/config/{os.environ['CONVERT_SDK_KEY']}",
    timeout=10.0,
)
config = resp.json()
# ...now you parse `config` and implement bucketing yourself.
```

With the SDK, the fetch, parse, and snapshot are one call (read the key from the
environment — never embed it):

```python
import os
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()
```

If you already hold a config payload (e.g. you cache it yourself), pass it as
`data=` and skip the network entirely — see [Initialization](initialization.md).

### Tracking: before and after

Raw REST sends one HTTP `POST` per conversion and leaves dedup, batching, and
retry to you. With the SDK, you record the conversion and let the queue handle
delivery. The sample below uses the offline docs fixture and an in-process
transport so it runs without network:

```python  # doctest: run
from convert_sdk import Core, SDKConfig, ConversionStatus
from tests.docs_sample_config import SAMPLE_CONFIG

class CollectingTransport:
    def __init__(self):
        self.sent = []
    def fetch_config(self, config):
        return SAMPLE_CONFIG
    def send_tracking(self, payload, *, sdk_key):
        self.sent.append(payload)
    def close(self):
        pass

transport = CollectingTransport()
core = Core(SDKConfig(data=SAMPLE_CONFIG), transport=transport).initialize()
context = core.create_context("visitor-001")

# Replaces a hand-built POST. No network call happens here — it enqueues.
result = context.track_conversion("purchase_completed", revenue=49.99)
assert result.status is ConversionStatus.QUEUED
assert result.tracked is True
_doc_rest_tracked = result.tracked

core.flush()                       # the single delivery point you control
assert transport.sent              # delivered as one batched request
core.close()
```

## What the SDK gives you over raw REST

These are the behaviors you no longer have to build and maintain yourself:

- **Batching.** Conversions accumulate in an in-process queue and are delivered
  together — by `flush()`, by `SDKConfig.batch_size` (default `10`), by an
  opt-in periodic timer, or at exit. Raw REST is one request per event.
- **Deduplication.** Conversions are deduplicated by `(visitor_id, goal_id)`, so
  a double-fire does not double-count. With raw REST you would track this state
  yourself. Use `force_multiple=True` for intentional repeats.
- **Lifecycle events.** Subscribe to `LifecycleEvent.API_QUEUE_RELEASED` (and
  others) through `Core.on` to observe delivery — handlers receive
  `(payload, error=None)`, so failures are visible. See
  [Queue control](queue-control.md).
- **Redaction.** Diagnostics and the log seam are redaction-safe by
  construction: the visitor reference is hashed and only allowlist-safe fields
  are exposed. See [Debugging](debugging.md). Raw REST logging is on you.

## Future async / framework support

If your service is async (FastAPI, an `asyncio` worker), you can adopt the SDK
**today**: it is sync-first, so call its methods from a coroutine via
`asyncio.to_thread()` (evaluation is non-blocking compute; config refresh runs
on its own daemon thread). A **native** async surface and framework-specific
helpers are **planned for Phase 3** and not yet implemented — see the
[roadmap](roadmap.md) and the [async & framework design intent](async.md). The
core SDK will always stay framework-free; framework helpers ship as separate
distributions.

## Where to go next

- [Initialization](initialization.md) — `sdk_key` vs `data`, the lifecycle
- [Evaluation](evaluation.md) — replacing your own bucketing/feature logic
- [Tracking](tracking.md) and [Queue control](queue-control.md) — the delivery model
- [Debugging](debugging.md) — typed diagnostics in place of log spelunking
- [Roadmap](roadmap.md) and [async & framework design intent](async.md) — the planned trajectory
