# Code Examples

Copy-paste examples for every public surface on the Python SDK's `Core`
and `Context`. Each section is self-contained.

Set up a context first:

```python
import os

from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))

context = core.create_context(
    "visitor-abc123",
    {"country": "US", "tier": "premium"},
)
```

## Running Experiences

Evaluate a single experience by key. Returns `ExperienceResult | None` —
`None` is a normal non-exceptional outcome (audience miss, location
miss, outside traffic).

```python
result = context.run_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

if result is None:
    # No bucketing match — render default UI
    pass
else:
    print(result.experience_key, result.variation_key, result.bucket_value)
```

Evaluate every applicable experience for the visitor at once:

```python
results = context.run_experiences(
    location_attributes={"path": "/checkout"},
)
for r in results:
    print(r.experience_key, "->", r.variation_key)
```

`run_experiences()` returns `list[ExperienceResult]`; an empty list when
no experiences matched.

## Running Features

Resolve a single feature flag. Variables are type-cast based on the
feature's declared schema (`boolean`, `integer`, `float`, `string`,
`json`).

```python
from convert_sdk import FeatureStatus

feature = context.run_feature(
    "checkout-banner",
    location_attributes={"path": "/checkout"},
)

if feature is None:
    show_banner = False
    title = "Welcome"
elif feature.status == FeatureStatus.ENABLED:
    show_banner = True
    title = feature.variables.get("title", "Welcome")
else:
    show_banner = False
    title = "Welcome"
```

Resolve every applicable feature at once:

```python
features = context.run_features(
    location_attributes={"path": "/checkout"},
)
for f in features:
    print(f.feature_key, f.status.value, dict(f.variables))
```

Disable variable type-casting (returns variables exactly as they appear
in the config) by passing `type_cast=False`:

```python
raw = context.run_feature("checkout-banner", type_cast=False)
```

## Tracking Conversions

Queue a conversion event for a goal. The event is enqueued in-process and
delivered when you flush the queue. Returns `ConversionResult` (does not
raise on success).

Basic conversion:

```python
result = context.track_conversion("purchase")

print(result.queued_event_count)        # number of events queued
print(result.duplicate_prevented)       # True if dedup blocked the event
```

Conversion with revenue and metadata:

```python
result = context.track_conversion(
    "purchase",
    conversion_data={
        "revenue": 49.99,
        "products_count": 2,
        "order_id": "ORD-7842",
    },
)
```

Repeat purchases (allow multiple transactions for the same goal):

```python
result = context.track_conversion(
    "purchase",
    conversion_data={"revenue": 29.99},
    force_multiple_transactions=True,
)
```

Handle a missing goal:

```python
from convert_sdk import GoalNotFoundError

try:
    context.track_conversion("unknown-goal")
except GoalNotFoundError as exc:
    print(exc.code, exc.context)
```

## Segments

Default segments are reporting dimensions carried with every context and
applied during evaluation:

```python
context.set_default_segments(["segment-premium-eu"])
```

Custom segments evaluate rule-based segment definitions and return only
the keys whose rules matched:

```python
matched = context.run_custom_segments(
    ["segment-premium-eu", "segment-mobile"],
    rule_data={"device": "mobile"},
)
# matched: tuple[str, ...] of the keys whose rules were satisfied
```

See the [Segments Manager](python-segments-manager.md) page for the
complete segment API.

## Visitor Properties

Visitor **attributes** drive audience and rule evaluation. Visitor
**properties** carry stable per-visitor metadata (e.g. an account id,
tier label) that you want stored alongside the visitor.

Both are stored on the context's underlying `DataStore` and reused on
the next `core.create_context(visitor_id)` call.

```python
context.update_visitor_attributes({"logged_in": True, "tier": "gold"})
context.update_visitor_properties({"crm_id": "ACC-1234"})

# Inspect current state
print(dict(context.visitor_attributes))
print(dict(context.visitor_properties))
```

By default both methods **merge** new keys onto existing state. Pass
`replace=True` to wipe and overwrite:

```python
context.update_visitor_attributes({"tier": "platinum"}, replace=True)
```

## Per-evaluation attribute overrides

Pass `visitor_attributes` to any evaluation method to merge temporary
overrides for that single call without mutating the stored state:

```python
result = context.run_experience(
    "beta-program",
    visitor_attributes={"beta_opt_in": True},
)
```

## Config Entity Lookup

Look up an entity from the loaded config by `key`:

```python
goal = context.get_config_entity("goals", "purchase")
if goal is not None:
    print(goal["id"], goal.get("name"))
```

Or by `id`:

```python
exp = context.get_config_entity_by_id("experiences", "exp-7821")
```

Both return `Mapping[str, Any] | None`. Common entity types:
`"experiences"`, `"features"`, `"goals"`, `"audiences"`, `"locations"`,
`"segments"`.

For a non-exception diagnosable lookup, use the `diagnose_*` variants:

```python
diag = context.diagnose_config_entity("experiences", "checkout-flow")
print(diag.resolved, diag.reason)   # bool, "resolved" or "not_found"
```

## Releasing Queues

Conversion events stay in-process until you explicitly flush. Call
`release_queues()` at end-of-request, end-of-task, or shutdown.

```python
flush = context.release_queues(reason="end_of_request")

print(flush.attempted)              # False if queue was empty
print(flush.delivered_event_count)  # events successfully POSTed
print(flush.delivered_batch_count)  # number of HTTP POSTs
print(flush.remaining_event_count)  # 0 on full success
```

Recommended flush points:

| Runtime              | Where to call `release_queues()`                          |
| -------------------- | --------------------------------------------------------- |
| Django / Flask (WSGI)| Response middleware, signal hook, or `teardown_request`   |
| FastAPI / Starlette  | `BackgroundTasks` or response middleware                  |
| AWS Lambda           | `finally` block before handler `return`                   |
| Celery task          | End of task body, `try/finally`                           |
| CLI script           | `try/finally` or `atexit` handler                         |

Tune batch size with `TrackingConfig(batch_size=N)`:

```python
from convert_sdk import Core, SDKConfig, TrackingConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        tracking=TrackingConfig(batch_size=25),
    )
)
```

## Events

Subscribe to lifecycle events emitted by `Core` to observe queue,
tracking, and refresh activity without modifying SDK internals.

```python
from convert_sdk import Core, LifecycleEvent, LifecycleEventPayload, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))


def on_queued(payload: LifecycleEventPayload) -> None:
    print("queued:", payload.details)


def on_released(payload: LifecycleEventPayload) -> None:
    print("delivered", payload.details.get("delivered_event_count"))


def on_delivery_failed(payload: LifecycleEventPayload) -> None:
    print("DELIVERY FAILED", payload.details.get("error_type"))


core.on(LifecycleEvent.TRACKING_EVENT_QUEUED, on_queued)
core.on(LifecycleEvent.QUEUE_RELEASED, on_released)
core.on(LifecycleEvent.TRACKING_DELIVERY_FAILED, on_delivery_failed)
```

Unsubscribe with `core.off(event, handler)`.

Available events:

| Event                       | Fires when                                                     |
| --------------------------- | -------------------------------------------------------------- |
| `CONFIG_UPDATED`            | A background refresh produced a new snapshot                   |
| `CONVERSION_CREATED`        | A conversion result is built (before enqueue)                  |
| `CONVERSION_DEDUPLICATED`   | Deduplication suppressed a duplicate conversion                |
| `TRACKING_EVENT_QUEUED`     | Events were added to the queue by `track_conversion()`         |
| `QUEUE_RELEASE_STARTED`     | `release_queues()` began draining a non-empty queue            |
| `QUEUE_RELEASED`            | All batches delivered successfully                             |
| `TRACKING_DELIVERY_FAILED`  | An HTTP transport error interrupted delivery                   |

Every handler receives a `LifecycleEventPayload`:

```python
@dataclass(frozen=True)
class LifecycleEventPayload:
    event: LifecycleEvent          # the enum value
    details: Mapping[str, Any]     # privacy-safe event-specific details
    occurred_at: datetime          # UTC timestamp
```

Visitor ids in `details` are replaced with a 16-character SHA-256 prefix
(`visitor_ref`), and sensitive keys are redacted before being included
in event payloads or diagnostic logs.

## Persistent DataStore

The default `InMemoryDataStore` keeps visitor state and goal-dedup
records inside the process — they reset on every restart. For
persistence across restarts (Redis, Postgres, Memcache, etc.), implement
the `DataStore` protocol and pass it to `Core`:

```python
import json
from dataclasses import asdict
from typing import Optional

from convert_sdk import Core, DataStore, SDKConfig
from convert_sdk.domain.context_state import ContextState


class RedisDataStore:
    """Sketch of a Redis-backed DataStore."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def load_context_state(self, visitor_id: str) -> Optional[ContextState]:
        raw = self._redis.get(f"convert:ctx:{visitor_id}")
        if raw is None:
            return None
        return ContextState(**json.loads(raw))

    def save_context_state(self, state: ContextState) -> None:
        self._redis.set(
            f"convert:ctx:{state.visitor_id}",
            json.dumps(asdict(state)),
        )

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        return bool(self._redis.sismember(f"convert:goals:{visitor_id}", goal_id))

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        self._redis.sadd(f"convert:goals:{visitor_id}", goal_id)


core = Core(
    SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]),
    data_store=RedisDataStore(redis_client),
)
```

`DataStore` is a structural Protocol — your class just needs to
implement `load_context_state`, `save_context_state`,
`has_tracked_goal`, and `mark_tracked_goal` with matching signatures.
No subclassing required.

## Diagnosing decisions

For each `run_*` method there is a matching `diagnose_*` method that
returns a typed diagnostic instead of `None`. Use them when you need to
understand *why* a visitor was not bucketed.

```python
exp_diag = context.diagnose_experience("checkout-flow")
print(exp_diag.resolved, exp_diag.reason, exp_diag.details)

feat_diag = context.diagnose_feature("checkout-banner")
print(feat_diag.resolved, feat_diag.reason)

goal_diag = context.diagnose_goal("purchase")
print(goal_diag.resolved, goal_diag.reason)
```

See [Return Types & DTOs](python-return-types.md) for the full diagnostic
shape and reason codes.

## Closing Core

Call `core.close()` to stop the background refresh thread (if any) and
release the HTTP client. By default it flushes the tracking queue first
with reason `"core_close"`.

```python
core.close()                           # flush + close
core.close(flush=False)                # close without flushing
core.close(flush_reason="shutdown")    # custom flush reason
```

Or use the context-manager form for automatic cleanup:

```python
with Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])) as core:
    context = core.create_context("visitor-1")
    context.run_experience("checkout-flow")
    context.release_queues(reason="end_of_request")
# core.close() runs automatically here
```

## Next steps

- [Return Types & DTOs](python-return-types.md) — typed result and
  diagnostic shapes
- [Segments Manager](python-segments-manager.md) — default and custom
  segment APIs
- [Configuration Options](python-configuration.md) — every config field
