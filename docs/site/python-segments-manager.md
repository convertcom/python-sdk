# Segments Manager

Segments are reporting dimensions that classify a visitor (mobile, EU,
premium tier, paid acquisition, …) so experiment results can be sliced
along consistent axes. The Python SDK exposes segments through methods
on `Context` — there is no separate `SegmentsManager` class to import.

## What "segments" mean in the SDK

There are two flavours, both stored on the same context:

- **Default segments.** A list of segment **keys** carried with the
  context and applied automatically during evaluation. Persisted on the
  `DataStore` so they survive across `core.create_context(visitor_id)`
  calls.
- **Custom segments.** Rule-based segment definitions evaluated against
  the visitor's attributes on demand. Returns the keys whose rules
  matched.

## Getting a context

Every segment API lives on `Context`, so create one first:

```python
import os

from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
context = core.create_context(
    "visitor-abc123",
    {"country": "US", "device": "mobile", "tier": "premium"},
)
```

## Default segments

Set the keys of named segment entities from the project config. These
keys are applied automatically during every subsequent evaluation on
this context.

```python
context.set_default_segments(["segment-premium", "segment-eu"])

# Read back what's stored
print(context.default_segments)   # ('segment-premium', 'segment-eu')
```

`set_default_segments()` accepts any `Sequence[str]`. Empty strings,
duplicates, and non-string entries are normalised away — the stored
result is a deduplicated `tuple[str, ...]` of non-empty keys in input
order.

Default segments are persisted on the `DataStore`. The next time you
call `core.create_context(visitor_id)` for the same visitor, the
default segments come back automatically.

## Custom segments

`run_custom_segments()` evaluates rule-based segment definitions from
the project config and returns only the keys whose rules were satisfied
by the current visitor's attributes.

```python
matched = context.run_custom_segments(
    ["segment-premium-eu", "segment-mobile", "segment-trial-expired"],
    rule_data={"device": "mobile", "trial_days_left": 0},
)

# matched: tuple[str, ...] of the keys whose rules were satisfied
```

`rule_data` is **per-call merge data** — its keys are merged on top of
the stored visitor attributes for this single evaluation only. Pass
`rule_data=None` (the default) to evaluate against the stored
attributes alone.

## Visitor attributes vs visitor properties

Both are mappings stored on the context, but they have different roles
in segment evaluation.

| Concept     | What it does                                                                | Where it's used                                                               |
| ----------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Attributes  | Drive audience matching, segment rule evaluation, and experience targeting | Segment rules read from here. Per-call `rule_data` merges on top.             |
| Properties  | Carry stable per-visitor metadata (CRM id, account tier label)              | Stored alongside the visitor; not consumed by segment rule evaluation.        |

Update either with merge-by-default semantics; pass `replace=True` to
wipe-and-overwrite:

```python
context.update_visitor_attributes({"logged_in": True, "tier": "gold"})
context.update_visitor_attributes({"tier": "platinum"}, replace=True)

context.update_visitor_properties({"crm_id": "ACC-1234"})
```

## Per-evaluation overrides

Every `run_*` method on `Context` accepts a `visitor_attributes` keyword
argument that merges temporary overrides for that single call without
mutating stored state. Useful for "what-if" evaluations:

```python
result = context.run_experience(
    "beta-program",
    visitor_attributes={"beta_opt_in": True},
)
```

The overrides apply only to that call. The next evaluation reverts to
the stored attributes.

## Looking up segment entities

Segments are stored alongside other entity types in the project config.
Look them up directly:

```python
segment = context.get_config_entity("segments", "segment-premium-eu")
if segment is not None:
    print(segment["id"], segment.get("name"))
```

Or get a non-exception diagnostic if you need to know whether the entity
existed and why a lookup might have missed:

```python
diag = context.diagnose_config_entity("segments", "segment-premium-eu")
print(diag.resolved, diag.reason)   # bool, "resolved" or "not_found"
```

## Reading current segment state

`Context` exposes the current segment state as read-only properties:

| Property             | Type                | Description                                                         |
| -------------------- | ------------------- | ------------------------------------------------------------------- |
| `default_segments`   | `tuple[str, ...]`   | The default segment keys currently carried with the context.        |
| `visitor_attributes` | `Mapping[str, Any]` | Current stored attributes (immutable view).                         |
| `visitor_properties` | `Mapping[str, Any]` | Current stored properties (immutable view).                         |

The mappings are immutable views; copy them if you need a mutable
snapshot:

```python
attrs = dict(context.visitor_attributes)
```

## How segments flow through evaluation

When you call `run_experience()`, `run_feature()`, or
`track_conversion()`, the SDK:

1. Resolves the **effective visitor attributes** by merging stored
   attributes with any per-call `visitor_attributes` override.
2. Resolves the **effective location attributes** the same way.
3. Applies **default segments** to the bucketing context so reports can
   slice along those dimensions.
4. Evaluates audience, location, and segment rules against the merged
   attributes.

Custom segments evaluated through `run_custom_segments()` are returned
to the caller — they are not persisted onto the context. To persist a
matched segment as a default, hand the result to `set_default_segments()`:

```python
matched = context.run_custom_segments(
    ["segment-premium-eu", "segment-mobile"],
    rule_data={"device": "mobile"},
)
if matched:
    context.set_default_segments(list(set(context.default_segments) | set(matched)))
```

## API summary

| Method on `Context`              | Purpose                                                                   |
| -------------------------------- | ------------------------------------------------------------------------- |
| `set_default_segments(keys)`     | Replace the default segment keys carried with this context.               |
| `default_segments` (property)    | Read the current default segment keys.                                    |
| `run_custom_segments(keys, *, rule_data=None)` | Evaluate rule-based segments and return matched keys.       |
| `update_visitor_attributes(...)` | Merge or replace visitor attributes (drives segment rule evaluation).     |
| `update_visitor_properties(...)` | Merge or replace visitor properties (stable per-visitor metadata).        |
| `get_config_entity("segments", key)` | Look up a segment definition by key.                                  |
| `diagnose_config_entity("segments", key)` | Non-exception variant of the lookup.                              |

## Next steps

- [Code Examples](python-code-examples.md) — full evaluation walkthrough
- [Return Types & DTOs](python-return-types.md) — typed result shapes
- [Configuration Options](python-configuration.md) — config dataclasses
