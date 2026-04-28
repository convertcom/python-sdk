# Migrating from the JavaScript SDK

This guide is for teams that are familiar with the Convert JavaScript SDK and
want to adopt the Python SDK — either porting backend Node.js code to Python or
sharing mental models with a JavaScript front end.

The two SDKs are **behaviorally equivalent**: the same `(visitor_id, experience_id)`
pair produces the same variation in both. The API surface uses Pythonic conventions
rather than JavaScript idioms.

## Concept map

| JavaScript SDK | Python SDK | Notes |
|----------------|------------|-------|
| `Core` constructor | `Core(SDKConfig(...))` | Same concept; Python uses a dataclass config object |
| `core.onReady()` | `core.is_ready` | Python init is synchronous; no async promise |
| `core.createContext(visitorId, attributes)` | `core.create_context(visitor_id, attributes)` | snake_case |
| `context.runExperience(key, opts)` | `context.run_experience(key, ...)` | Returns typed dataclass, not plain dict |
| `context.runExperiences(opts)` | `context.run_experiences(...)` | Returns `list[ExperienceResult]` |
| `context.runFeature(key, opts)` | `context.run_feature(key, ...)` | Returns `FeatureResult \| None` |
| `context.runFeatures(opts)` | `context.run_features(...)` | Returns `list[FeatureResult]` |
| `context.trackConversion(key, data)` | `context.track_conversion(key, conversion_data=...)` | Data shape differs — see below |
| `context.setDefaultSegments(segments)` | `context.set_default_segments(segment_keys)` | Takes a sequence of string keys |
| `context.runCustomSegments(keys, attrs)` | `context.run_custom_segments(keys, rule_data=...)` | Returns `tuple[str, ...]` |
| `core.on(event, handler)` | `core.on(LifecycleEvent.X, handler)` | Typed enum instead of string |
| `core.off(event, handler)` | `core.off(LifecycleEvent.X, handler)` | Same pattern |
| `context.releaseQueues()` | `context.release_queues(reason=...)` | Optional reason string |

## Initialization

**JavaScript:**

```javascript
import { Core } from '@convertcom/js-sdk';

const core = new Core({ sdkKey: process.env.CONVERT_SDK_KEY });
await core.onReady();
```

**Python:**

```python
import os
from convert_sdk import Core, SDKConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        environment="production",
    )
)
# core.is_ready is True immediately — init is synchronous
assert core.is_ready
```

Python's `Core.__init__()` is synchronous and blocking. There is no `on_ready()`
coroutine because initialization does not use an async event loop. If the config
fetch fails, `ConfigLoadError` is raised at construction time, not deferred.

## Context creation

**JavaScript:**

```javascript
const context = core.createContext('visitor-abc123', {
  browser: 'chrome',
  country: 'US',
});
```

**Python:**

```python
context = core.create_context(
    "visitor-abc123",
    {"browser": "chrome", "country": "US"},
)
```

The Python `Context` object is reusable across multiple evaluations and mutable
via `update_visitor_attributes()`. There is no builder pattern; attributes are
supplied at creation time and updated explicitly.

## Running experiences

**JavaScript:**

```javascript
const result = context.runExperience('checkout-flow', {
  locationAttributes: { path: '/checkout' },
});

if (result) {
  console.log(result.variationKey);
}
```

**Python:**

```python
result = context.run_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

if result is not None:
    print(result.variation_key, result.bucket_value)
```

The Python result is a frozen dataclass (`ExperienceResult`) rather than a plain
dict. All fields are typed — see [Evaluation](evaluation.md#experienceresult-fields).

## Running features

**JavaScript:**

```javascript
const feature = context.runFeature('checkout-banner', {
  locationAttributes: { path: '/checkout' },
});

if (feature) {
  console.log(feature.status, feature.variables);
}
```

**Python:**

```python
feature = context.run_feature(
    "checkout-banner",
    location_attributes={"path": "/checkout"},
)

if feature is not None:
    print(feature.status.value)       # "enabled" or "disabled"
    print(dict(feature.variables))    # type-cast variable dict
```

`FeatureStatus` is an enum exposed at `convert_sdk.FeatureStatus`. Compare
against the enum members (`feature.status == FeatureStatus.ENABLED`) for type
safety — this is the form the rest of the documentation uses.

## Tracking conversions

**JavaScript:**

```javascript
context.trackConversion('purchase', {
  goalData: [
    { key: 'revenue', value: 49.99 },
    { key: 'products_count', value: 2 },
  ],
});
```

**Python:**

```python
result = context.track_conversion(
    "purchase",
    conversion_data={
        "revenue": 49.99,
        "products_count": 2,
    },
)
```

The Python SDK accepts `conversion_data` as a flat `Mapping[str, Any]` rather
than a list of `{key, value}` objects. The SDK serializes this into the
`goalData` wire format automatically before POSTing.

## Segments

**JavaScript:**

```javascript
context.setDefaultSegments({ browser: 'CH', country: 'US' });
const matched = context.runCustomSegments(['segment-key-1'], {});
```

**Python:**

```python
context.set_default_segments(["segment-premium-eu"])
matched = context.run_custom_segments(
    ["segment-premium-eu", "segment-mobile"],
    rule_data={"device": "mobile"},
)
# matched: tuple[str, ...] — only the keys whose rules were satisfied
```

The Python SDK's `set_default_segments()` takes a sequence of segment key strings
(not a dict of browser/country fields). Visitor attributes for rule matching are
passed as `visitor_attributes` at context creation time or as `rule_data` in
`run_custom_segments()`.

## Lifecycle events

**JavaScript:**

```javascript
core.on('conversionCreated', (payload) => {
  console.log(payload.goalId);
});
```

**Python:**

```python
from convert_sdk import LifecycleEvent, LifecycleEventPayload

def on_conversion(payload: LifecycleEventPayload) -> None:
    print(payload.event.value, payload.details)

core.on(LifecycleEvent.CONVERSION_CREATED, on_conversion)
```

Python uses a typed `LifecycleEvent` enum (not bare strings). The handler
receives a `LifecycleEventPayload` dataclass with `.event`, `.details`, and
`.occurred_at` fields.

## Queue release

**JavaScript:**

```javascript
await context.releaseQueues();
```

**Python:**

```python
flush_result = context.release_queues(reason="end_of_request")
print(flush_result.delivered_event_count)
```

Python's `release_queues()` is synchronous. There is no async variant in the
default transport. See [Extending](extending.md) for how to replace the transport
with an async-capable implementation.

## Deliberate Pythonic differences

| Area | JavaScript | Python | Why |
|------|------------|--------|-----|
| Naming | `camelCase` | `snake_case` | PEP 8 convention |
| Results | plain `object` | frozen `dataclass` | Immutability, type safety |
| Async | `Promise` / `await` | synchronous (blocking) | Python SDK is sync-first |
| Config object | `{sdkKey, environment, ...}` | `SDKConfig(sdk_key=..., environment=...)` | Typed frozen dataclass |
| Errors | thrown `Error` objects | typed exceptions with `.code` and `.context` | Structured error handling |
| Segment input | `{browser: 'CH'}` dict | sequence of string keys | Segments are config entities |
| Diagnostics | console-level debug | `logging` integration | Python stdlib conventions |
| Extension | subclassing / plugins | Protocol implementations | Structural typing |

## Behavioral equivalence

The bucketing algorithm is identical between the two SDKs. For the same
`(visitor_id, experience_id)` pair, both SDKs compute the same bucket value and
select the same variation. This is verified by the parity test suite at
[`tests/parity/`](../tests/parity/).

The hash input format is `f"{experience_id}{visitor_id}"` (experience id
concatenated before visitor id) with MurmurHash3 32-bit seed `9999`. If you
compute the bucket value manually in JavaScript and compare it to
`ExperienceResult.bucket_value` in Python, the values will match.

## Future async / framework support

The MVP is sync-first. An async public API (`AsyncCore` / `AsyncContext`)
and framework-specific helpers (`convert-sdk-django`,
`convert-sdk-fastapi`, `convert-sdk-flask`) are planned for Phase 3 and
will share the same evaluation core, parity contracts, and adapter
Protocols as the sync surface. See [Roadmap](roadmap.md) and
[Async and framework integrations](async.md) for the design intent.

## What to read next

- [Evaluation](evaluation.md) — full `run_experience()` / `run_feature()` reference
- [Tracking](tracking.md) — `track_conversion()` options and wire format
- [Debugging](debugging.md) — `diagnose_experience()` replaces JS SDK debug mode
- [Extending](extending.md) — replacing transport/storage adapters
- [Roadmap](roadmap.md) — what is shipped, what is planned
