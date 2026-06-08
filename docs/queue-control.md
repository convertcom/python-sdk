# Queue control

`track_conversion` never sends over the network — it enqueues. You control
**when** queued events are delivered. The default lifecycle is
**explicit-flush-only**, which is safe in every runtime. Choose the release
strategy that fits your process model; see [Runtime integration](runtime-integration.md)
for per-runtime recommendations.

## Release triggers

| Trigger | How to enable | When it fires |
|---------|---------------|---------------|
| Explicit flush | always available | `core.flush()` is called |
| Batch size | `SDKConfig.batch_size` (default `10`) | the queue reaches `batch_size` events |
| Periodic timer | `SDKConfig.auto_flush_interval_ms` (opt-in) | a daemonic timer ticks |
| Process exit | best-effort `atexit` hook | the interpreter shuts down |

## Explicit flush

`flush()` delivers queued events through the configured transport and clears the
queue on success. A flush on an empty queue is a safe no-op — no transport call,
no error.

The sample below injects a small in-process transport so it runs offline; in
production the SDK's built-in `httpx` transport delivers to the Convert tracking
endpoint. A transport is injected with the **keyword-only** `transport=`
argument — see [Extending](extending.md) for the full extension contract.

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

class CollectingTransport:
    """A minimal Transport that records deliveries instead of sending them."""
    def __init__(self):
        self.delivered = []
    def fetch_config(self, config):
        return SAMPLE_CONFIG
    def send_tracking(self, payload, *, sdk_key):
        self.delivered.append(payload)
    def close(self):
        pass

transport = CollectingTransport()
core = Core(SDKConfig(data=SAMPLE_CONFIG), transport=transport).initialize()
context = core.create_context("visitor-001")

context.track_conversion("purchase_completed", revenue=49.99)
core.flush()        # delivers the queued event through the transport
core.flush()        # safe no-op on an empty queue
assert transport.delivered            # the conversion was delivered exactly once
core.close()
```

## Batch-size release

Set `batch_size` so the queue self-releases once it fills. This bounds memory
and latency without any explicit `flush()` calls in your hot path:

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG, batch_size=5)).initialize()
context = core.create_context("visitor-001")
# Up to 5 distinct conversions queue before a batch-size release fires.
core.close()
```

## Periodic timer (opt-in)

`auto_flush_interval_ms` starts a daemonic timer that flushes on an interval.
It is opt-in because a background thread is not appropriate for every runtime
(e.g. short-lived Lambda invocations). Leave it unset for explicit-flush-only.

```python
from convert_sdk import Core, SDKConfig

# Flush every 2 seconds in a long-lived server process:
core = Core(SDKConfig(data=config_data, auto_flush_interval_ms=2000)).initialize()
```

## Reacting to queue releases

Subscribe to `LifecycleEvent.API_QUEUE_RELEASED` through `Core.on` to observe
when the API tracking queue is released (for metrics, logging, or tests):

Lifecycle handlers receive `(payload, error=None)` — `error` is non-`None` only
when the release failed:

```python  # doctest: run
from convert_sdk import Core, SDKConfig, LifecycleEvent
from tests.docs_sample_config import SAMPLE_CONFIG

class CollectingTransport:
    def fetch_config(self, config):
        return SAMPLE_CONFIG
    def send_tracking(self, payload, *, sdk_key):
        pass
    def close(self):
        pass

released = []

core = Core(SDKConfig(data=SAMPLE_CONFIG), transport=CollectingTransport()).initialize()
core.on(
    LifecycleEvent.API_QUEUE_RELEASED,
    lambda payload, error=None: released.append(payload),
)

context = core.create_context("visitor-001")
context.track_conversion("purchase_completed")
core.flush()

assert released            # the release fired
core.close()
```

`LifecycleEvent.DATA_STORE_QUEUE_RELEASED` is the analogous signal for the
persistence-side queue.

## Public API this guide relies on

- `Core.flush()` — explicit release; no-op on an empty queue
- `SDKConfig.batch_size`, `SDKConfig.auto_flush_interval_ms`
- `Core.on(LifecycleEvent, handler)` and the
  `LifecycleEvent.API_QUEUE_RELEASED` / `DATA_STORE_QUEUE_RELEASED` signals
- The `atexit` best-effort release at interpreter shutdown
