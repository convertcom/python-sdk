# Evaluation

The SDK resolves experiences and feature flags entirely in-process using the
config snapshot loaded at initialization. There are no per-evaluation network
calls.

Relevant source files:

- [`src/convert_sdk/context.py`](../src/convert_sdk/context.py) — `Context`
- [`src/convert_sdk/domain/results.py`](../src/convert_sdk/domain/results.py) —
  `ExperienceResult`, `FeatureResult`, `FeatureStatus`, `ExperienceDiagnostic`,
  `FeatureDiagnostic`
- [`src/convert_sdk/evaluation/bucketing.py`](../src/convert_sdk/evaluation/bucketing.py) —
  deterministic bucketing algorithm

## Creating a visitor context

```python
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(config_data=project_config))

context = core.create_context(
    "visitor-abc123",
    {"tier": "premium", "country": "US"},
)
```

When `visitor_attributes` is supplied to `create_context()`, the stored
attributes for that visitor are *replaced* (not merged) — only
`visitor_properties` and `default_segments` carry over from any previously
stored state. To merge new attributes onto existing ones, omit the second
argument from `create_context()` and call
`context.update_visitor_attributes({...})` afterwards (it merges by default;
pass `replace=True` to wipe and overwrite).

`Context` is reusable — call multiple evaluation methods on the same instance
within a request lifecycle.

## Running a single experience

```python
result = context.run_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

if result is None:
    # visitor did not qualify (audience miss, location miss, or outside traffic)
    pass
else:
    print(result.experience_key, result.variation_key, result.bucket_value)
```

`run_experience()` returns `ExperienceResult | None`. A `None` result is a
normal non-exceptional outcome — it means the visitor was not bucketed into that
experience.

### ExperienceResult fields

| Field | Type | Description |
|-------|------|-------------|
| `experience_id` | `str` | Internal config id |
| `experience_key` | `str` | Human-readable key from the dashboard |
| `experience_name` | `str \| None` | Display name |
| `variation_id` | `str` | Internal variation id |
| `variation_key` | `str` | Human-readable variation key |
| `variation_name` | `str \| None` | Display name |
| `bucket_value` | `int` | The 0–9999 bucket value that selected this variation |

## Running all experiences at once

```python
results = context.run_experiences(
    location_attributes={"path": "/checkout"},
)
# results: list[ExperienceResult], empty list when no match
for r in results:
    print(r.experience_key, r.variation_key)
```

## Running a single feature

```python
feature = context.run_feature(
    "checkout-banner",
    location_attributes={"path": "/checkout"},
)

if feature is None:
    pass  # feature disabled or visitor not in any backing experience
else:
    print(feature.status.value)        # "enabled" or "disabled"
    print(feature.variables)           # immutable Mapping[str, Any]
    print(feature.variables.get("title"))
```

### FeatureResult fields

| Field | Type | Description |
|-------|------|-------------|
| `feature_id` | `str` | Internal config id |
| `feature_key` | `str` | Human-readable key |
| `feature_name` | `str \| None` | Display name |
| `status` | `FeatureStatus` | `ENABLED` or `DISABLED` |
| `variables` | `Mapping[str, Any]` | Type-cast feature variables |
| `experience_id` | `str \| None` | Backing experience, if any |
| `experience_key` | `str \| None` | Backing experience key |
| `variation_key` | `str \| None` | Backing variation key |

### FeatureStatus enum

```python
from convert_sdk import FeatureStatus

if feature.status == FeatureStatus.ENABLED:
    ...
```

### Variable type casting

Variables are type-cast based on the `type` field declared in the config. The
supported types are `boolean`, `integer`, `float`, `string`, and `json`. Pass
`type_cast=False` to `run_feature()` to skip the cast and receive each variable
as it appears in the config snapshot (typically a string from the JSON payload,
but whatever Python type the config produced — no coercion is performed).

## Running all features at once

```python
features = context.run_features(
    location_attributes={"path": "/checkout"},
)
for f in features:
    print(f.feature_key, f.status.value, dict(f.variables))
```

## Per-evaluation visitor attribute overrides

You can pass `visitor_attributes` directly to any evaluation method to merge
temporary overrides without mutating the stored context state:

```python
result = context.run_experience(
    "beta-program",
    visitor_attributes={"beta_opt_in": True},
)
```

These overrides are not persisted; they apply only to that single evaluation call.

## Segments

### Default segments

Default segments are keys of named segment entities from the config. They are
carried with every context and applied automatically during evaluation.

```python
context.set_default_segments(["segment-premium-eu"])
```

### Custom segment evaluation

`run_custom_segments()` evaluates a list of segment keys against the visitor's
attributes and returns only the keys that matched:

```python
matched = context.run_custom_segments(
    ["segment-premium-eu", "segment-mobile"],
    rule_data={"device": "mobile"},
)
# matched: tuple[str, ...] of the keys whose rules were satisfied
```

## Bucketing algorithm

The SDK uses a pure-Python MurmurHash3 32-bit implementation (no external
dependency). The hash input is `f"{experience_id}{visitor_id}"` with seed `9999`.
The resulting unsigned 32-bit value is divided by `4294967296` and multiplied by
`10000` to produce an integer bucket value in the range `[0, 9999]`.

Variation selection walks the variation list in order, accumulating
`traffic_allocation` (a percentage value multiplied by 100) until the bucket
value falls below the cumulative total. This matches the JavaScript SDK's
algorithm exactly, ensuring the same visitor/experience pair resolves to the same
variation across all Convert SDKs.

Source: [`src/convert_sdk/evaluation/bucketing.py`](../src/convert_sdk/evaluation/bucketing.py)

## Diagnosable outcomes

When you need to understand *why* a visitor was not bucketed, use the `diagnose_*`
variants instead of `run_*`:

```python
diag = context.diagnose_experience("checkout-flow")
print(diag.resolved)   # bool
print(diag.reason)     # e.g. "audience_miss", "location_miss", "outside_traffic"
print(diag.result)     # ExperienceResult | None
print(diag.details)    # immutable Mapping with bucketing details
```

See [Debugging](debugging.md) for the full list of reason codes and how to use
diagnostic results in support workflows.

## What to read next

- [Tracking](tracking.md) — record conversions once you have a variation
- [Queue control](queue-control.md) — flush queued events at end-of-request
- [Debugging](debugging.md) — use diagnostic types to trace evaluation decisions
