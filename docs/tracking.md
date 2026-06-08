# Conversion tracking

`track_conversion` records a goal conversion for the visitor. It is lightweight
and synchronous: it resolves the goal against the loaded config, deduplicates by
`(visitor_id, goal_id)`, and appends to an in-process batch queue. **No network
call happens on `track_conversion`** — queued events are delivered when the
queue is released (see [Queue control](queue-control.md)).

It returns a typed `ConversionResult` whose `status` is one of:

| `ConversionStatus` | `tracked` | `reason` | Meaning |
|--------------------|-----------|----------|---------|
| `QUEUED` | `True` | `None` | The goal resolved and an event was enqueued. |
| `DEDUPLICATED` | `False` | `"deduplicated"` | A default-mode duplicate for an already-tracked `(visitor, goal)`. |
| `GOAL_NOT_FOUND` | `False` | `"goal_not_found"` | The goal key is absent from the loaded config (a diagnosable non-exception outcome). |

> The runnable sample imports `SAMPLE_CONFIG` from the docs fixture, which
> declares the `purchase_completed` goal.

## Tracking a conversion

```python  # doctest: run
from convert_sdk import Core, SDKConfig, ConversionStatus
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

first = context.track_conversion("purchase_completed", revenue=49.99)
assert first.status is ConversionStatus.QUEUED
assert first.tracked is True
assert first.reason is None
_doc_first_tracked = first.tracked          # True

# A default duplicate for the same (visitor, goal) is suppressed:
second = context.track_conversion("purchase_completed")
assert second.status is ConversionStatus.DEDUPLICATED
assert second.tracked is False
assert second.reason == "deduplicated"
_doc_second_tracked = second.tracked        # False

# An unknown goal is a typed miss, not an exception:
missing = context.track_conversion("ghost_goal")
assert missing.status is ConversionStatus.GOAL_NOT_FOUND
assert missing.reason == "goal_not_found"

# Deliver queued events explicitly (the canonical control point):
core.flush()
core.close()
```

## Revenue and repeated transactions

Dedup is by goal **identity**, not payload content — a differing `revenue` or
`conversion_data` does not defeat it. Use `force_multiple=True` to re-track an
already-tracked goal (for repeated revenue / transactions):

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

context.track_conversion("purchase_completed", revenue=49.99)
# force_multiple re-tracks despite the prior conversion:
again = context.track_conversion(
    "purchase_completed",
    revenue=10.0,
    conversion_data={"transaction_id": "txn-2"},
    force_multiple=True,
)
assert again.tracked is True
core.flush()
core.close()
```

## Attribution

A tracked conversion carries the visitor's attribution context at conversion
time — the active default segments (see [`set_segments`](evaluation.md#segments))
and the active variation/bucketing assignments. Set segments and run
experiences before tracking so the conversion is attributed correctly.

## Public API this guide relies on

- `Context.track_conversion(goal_key, *, revenue=..., conversion_data=...,
  force_multiple=...)` → `ConversionResult`
- `ConversionResult` — `.status`, `.tracked`, `.reason`, `.event`
- `ConversionStatus` — `QUEUED`, `DEDUPLICATED`, `GOAL_NOT_FOUND`
- `Core.flush()` — delivers queued events
