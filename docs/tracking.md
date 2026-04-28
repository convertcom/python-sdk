# Tracking

Conversion tracking records when a visitor completes a goal. Events are queued
in-process and delivered in batches when you explicitly flush the queue.

Relevant source files:

- [`src/convert_sdk/context.py`](../src/convert_sdk/context.py) —
  `Context.track_conversion()`, `Context.release_queues()`
- [`src/convert_sdk/domain/results.py`](../src/convert_sdk/domain/results.py) —
  `ConversionResult`, `ConversionEvent`, `TrackingFlushResult`
- [`src/convert_sdk/tracking/queue.py`](../src/convert_sdk/tracking/queue.py) —
  `TrackingQueue`
- [`src/convert_sdk/tracking/payloads.py`](../src/convert_sdk/tracking/payloads.py) —
  `serialize_tracking_payload()`

## Basic conversion

```python
result = context.track_conversion("purchase")

print(result.queued_event_count)     # number of events queued
print(result.duplicate_prevented)   # True if deduplication blocked the event
```

`track_conversion()` always returns `ConversionResult` — it does not raise if
the goal exists. A `GoalNotFoundError` is raised only when the `goal_key` is
absent from the config snapshot.

## Conversion with revenue data

Pass a `conversion_data` mapping to attach arbitrary key/value pairs to the
conversion event. Common use: recording revenue, product counts, or order ids.

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

Value types accepted in `conversion_data`:

| Accepted | Not accepted |
|----------|--------------|
| `int`, `float`, `str` | `bool` |
| `tuple[str, ...]` / `list[str]` (tags) | `dict`, `bytes`, other sequences |

Booleans and non-string sequence items raise `ConversionDataError`.

## ConversionResult fields

| Field | Type | Description |
|-------|------|-------------|
| `events` | `tuple[ConversionEvent, ...]` | Typed events queued for delivery |
| `duplicate_prevented` | `bool` | `True` when deduplication suppressed the event |
| `queued_event_count` | `int` | Number of events added to the queue |
| `event` | `ConversionEvent \| None` | Property: the most-useful single event |

When `conversion_data` is supplied, the SDK creates two events per conversion:
one base conversion event (no data, for goal attribution) and one transaction
event (carries the `conversion_data`). Both share the same `goal_id`.

## ConversionEvent fields

| Field | Type | Description |
|-------|------|-------------|
| `visitor_id` | `str` | Visitor identifier |
| `goal_id` | `str` | Internal config id of the goal |
| `goal_key` | `str` | Human-readable goal key |
| `goal_name` | `str \| None` | Display name |
| `account_id` | `str \| None` | Sourced from the config snapshot |
| `project_id` | `str \| None` | Sourced from the config snapshot |
| `conversion_data` | `Mapping[str, Any]` | Revenue / metadata payload |
| `bucketing_data` | `Mapping[str, str]` | `{experience_id: variation_id}` attribution |
| `event_type` | `str` | `"conversion"` |

`bucketing_data` is built by re-evaluating all active experiences at the moment
of `track_conversion()`. This means the conversion event carries attribution for
every experience the visitor was currently bucketed into.

## Deduplication

By default, each `(visitor_id, goal_id)` pair is tracked only once per `Core`
instance lifetime. Subsequent calls to `track_conversion()` with the same visitor
and goal are silently deduplicated and return `ConversionResult(duplicate_prevented=True)`.

To allow multiple transactions for the same goal (e.g. repeat purchases with
different revenue amounts), pass `force_multiple_transactions=True`:

```python
result = context.track_conversion(
    "purchase",
    conversion_data={"revenue": 29.99},
    force_multiple_transactions=True,
)
```

With `force_multiple_transactions=True`, the base conversion event is still sent
only once, but an additional transaction event is queued for each subsequent call
that includes `conversion_data`.

Deduplication state is stored in the `DataStore`. The default `InMemoryDataStore`
resets between process restarts. If you need persistence across restarts, supply a
custom `DataStore` implementation — see [Extending](extending.md).

## Flushing the queue

Events are not sent to the network until you call `release_queues()`:

```python
flush_result = context.release_queues(reason="end_of_request")

print(flush_result.attempted)              # False if the queue was empty
print(flush_result.delivered_event_count)  # events successfully POSTed
print(flush_result.delivered_batch_count)  # batches sent
print(flush_result.remaining_event_count)  # 0 on full success
```

See [Queue control](queue-control.md) for batching configuration and lifecycle
event hooks for delivery monitoring.

## TrackingFlushResult fields

| Field | Type | Description |
|-------|------|-------------|
| `attempted` | `bool` | `False` if the queue was empty, no POST was made |
| `delivered_event_count` | `int` | Total events delivered |
| `delivered_batch_count` | `int` | Number of HTTP POST requests made |
| `remaining_event_count` | `int` | Events still in queue (non-zero on partial failure) |
| `reason` | `str \| None` | The string passed to `release_queues()` |

## Error types

| Error | When raised |
|-------|-------------|
| `GoalNotFoundError` | `goal_key` not present in the config snapshot |
| `ConversionDataError` | `conversion_data` contains invalid types |
| `TrackingError` | Base class for tracking errors |

```python
from convert_sdk import GoalNotFoundError

try:
    context.track_conversion("unknown-goal")
except GoalNotFoundError as exc:
    print(exc.code)     # "goal.not_found"
    print(exc.context)  # {"reason": "goal_not_found", "available_goal_count": N}
```

## Payload wire format

The SDK serializes batches into the following JSON structure before POSTing to
the tracking endpoint:

```json
{
    "source": "python-sdk",
    "enrichData": true,
    "accountId": "...",
    "projectId": "...",
    "visitors": [
        {
            "visitorId": "...",
            "events": [
                {
                    "eventType": "conversion",
                    "data": {
                        "goalId": "...",
                        "goalData": [{"key": "revenue", "value": 49.99}],
                        "bucketingData": {"exp-id": "var-id"}
                    }
                }
            ]
        }
    ]
}
```

Source:
[`src/convert_sdk/tracking/payloads.py`](../src/convert_sdk/tracking/payloads.py)

## What to read next

- [Queue control](queue-control.md) — batch sizing, lifecycle events, flush timing
- [Debugging](debugging.md) — `diagnose_goal()` for non-exception goal lookups
- [Support workflows](support-workflows.md) — what to include when reporting a tracking issue
