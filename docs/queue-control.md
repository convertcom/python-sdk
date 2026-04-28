# Queue Control

The SDK queues conversion events in-process and delivers them in HTTP POST
batches only when you explicitly call `release_queues()`. This gives you control
over when network calls happen and how to handle delivery failures.

Relevant source files:

- [`src/convert_sdk/tracking/queue.py`](../src/convert_sdk/tracking/queue.py) —
  `TrackingQueue`, `TrackingFlushResult`
- [`src/convert_sdk/events.py`](../src/convert_sdk/events.py) —
  `LifecycleEvent`, `LifecycleEventPayload`
- [`src/convert_sdk/config.py`](../src/convert_sdk/config.py) — `TrackingConfig`
- [`src/convert_sdk/core.py`](../src/convert_sdk/core.py) — `Core.on()`, `Core.off()`

## Explicit flush

```python
flush_result = context.release_queues(reason="end_of_request")

if flush_result.attempted:
    print(f"Delivered {flush_result.delivered_event_count} events "
          f"in {flush_result.delivered_batch_count} batches")
else:
    print("Queue was empty — nothing sent")
```

`release_queues()` is synchronous and blocking. It drains the entire queue
before returning. If the HTTP transport raises during delivery, the exception
propagates and the un-delivered events remain in the queue.

The `reason` string is optional and is carried through lifecycle events and
diagnostic logs. Use it to identify the flush trigger in your logs
(`"end_of_request"`, `"shutdown"`, `"test_teardown"`, etc.).

## When to flush

The queue is not flushed automatically. Common flush points:

| Runtime | Recommended flush point |
|---------|------------------------|
| Django / Flask (WSGI) | Response middleware `process_response()` hook |
| FastAPI / Starlette (ASGI) | Background task or response middleware |
| AWS Lambda | End of handler before `return` |
| CLI / script | `finally` block after main logic |
| Long-running service | Periodic background thread + shutdown hook |

```python
# Django middleware example
class ConvertFlushMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        context = getattr(request, "convert_context", None)
        if context is not None:
            context.release_queues(reason="response_sent")
        return response
```

## Batch size

The `TrackingConfig.batch_size` field (default `10`) controls the maximum number
of events included in a single tracking POST. If the queue contains more events
than `batch_size`, multiple POST requests are made sequentially in a single
`release_queues()` call.

```python
from convert_sdk import Core, SDKConfig, TrackingConfig

core = Core(
    SDKConfig(
        config_data=project_config,
        tracking=TrackingConfig(batch_size=25),
    )
)
```

## Lifecycle events

Subscribe to lifecycle events on the `Core` instance to observe queue activity
without modifying SDK internals:

```python
from convert_sdk import Core, SDKConfig, LifecycleEvent, LifecycleEventPayload

core = Core(SDKConfig(config_data=project_config))

def on_event_queued(payload: LifecycleEventPayload) -> None:
    print(payload.event.value, payload.details)

def on_released(payload: LifecycleEventPayload) -> None:
    print("delivered", payload.details.get("delivered_event_count"))

def on_delivery_failed(payload: LifecycleEventPayload) -> None:
    print("DELIVERY FAILURE", payload.details.get("error_type"))

core.on(LifecycleEvent.TRACKING_EVENT_QUEUED, on_event_queued)
core.on(LifecycleEvent.QUEUE_RELEASED, on_released)
core.on(LifecycleEvent.TRACKING_DELIVERY_FAILED, on_delivery_failed)
```

Unsubscribe with `core.off(event, handler)`.

### Available lifecycle events

| Event | Fired when |
|-------|-----------|
| `TRACKING_EVENT_QUEUED` | Events are added to the queue by `track_conversion()` |
| `QUEUE_RELEASE_STARTED` | `release_queues()` begins draining a non-empty queue |
| `QUEUE_RELEASED` | All batches delivered successfully |
| `TRACKING_DELIVERY_FAILED` | An HTTP transport error interrupted delivery |
| `CONVERSION_CREATED` | A conversion result is built (before enqueue) |
| `CONVERSION_DEDUPLICATED` | Deduplication prevented a duplicate conversion event |

### LifecycleEventPayload

Every handler receives a `LifecycleEventPayload` dataclass:

```python
@dataclass(frozen=True)
class LifecycleEventPayload:
    event: LifecycleEvent        # the event enum value
    details: Mapping[str, Any]   # privacy-safe event-specific details
    occurred_at: datetime        # UTC timestamp
```

Details are always privacy-safe: visitor ids are replaced with a 16-character
SHA-256 prefix (`visitor_ref`), and sensitive keys are redacted before being
included in event payloads or diagnostic logs.

## Delivery failure handling

When `release_queues()` raises (e.g. `httpx.TransportError`), the un-delivered
batch remains in the queue. You can retry by calling `release_queues()` again.
The `TRACKING_DELIVERY_FAILED` lifecycle event fires before the exception
propagates, so you can log or alert from a handler without wrapping every
`release_queues()` call in a `try/except`.

```python
def on_delivery_failed(payload: LifecycleEventPayload) -> None:
    remaining = payload.details.get("remaining_event_count", "?")
    error = payload.details.get("error_type", "unknown")
    logger.error("tracking delivery failed: %s (%s events remaining)", error, remaining)

core.on(LifecycleEvent.TRACKING_DELIVERY_FAILED, on_delivery_failed)

try:
    context.release_queues(reason="end_of_request")
except Exception:
    pass  # handler already logged; events remain in queue for next flush
```

## Runtime compatibility matrix

| Runtime | Queue delivery | Notes |
|---------|----------------|-------|
| Django (sync WSGI) | Sync, blocking in request thread | Use middleware or signal hook |
| Flask (sync WSGI) | Sync, blocking in request thread | Use `@app.teardown_request` |
| FastAPI (ASGI, sync path) | Sync, blocks event loop thread | Use `BackgroundTasks` or middleware |
| AWS Lambda | Sync, blocking before `return` | Add `release_queues()` in `finally` |
| Celery task | Sync, blocking in worker thread | Call at end of task body |
| CLI script | Sync, call explicitly | Use `try/finally` or `atexit` |

The default `HttpxTransport` uses `httpx.Client` (synchronous). There is no
built-in async transport; for async-first runtimes, implement the `Transport`
protocol with an async-capable client — see [Extending](extending.md).

## What to read next

- [Tracking](tracking.md) — how events are created and deduplicated
- [Extending](extending.md) — replace the transport for async or custom delivery
- [Debugging](debugging.md) — read diagnostic log events from the queue lifecycle
