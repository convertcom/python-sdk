# Return Types & DTOs

Every public surface on the Python SDK returns a typed dataclass or
enum. All result types are **frozen** (immutable) and importable from
the top-level `convert_sdk` package.

This page is the reference for those shapes. Pair it with
[Code Examples](python-code-examples.md) for usage patterns.

## Frozen dataclasses

Each DTO is declared with `@dataclass(frozen=True)`. Field access is
plain attribute syntax (`result.experience_key`); attempting to mutate
a field raises `dataclasses.FrozenInstanceError`.

### `ExperienceResult`

Returned by `Context.run_experience()` (single) and
`Context.run_experiences()` (list). Identifies the bucketed variation
for an experience.

| Field             | Type            | Description                                                    |
| ----------------- | --------------- | -------------------------------------------------------------- |
| `experience_id`   | `str`           | Internal config id of the experience.                          |
| `experience_key`  | `str`           | Human-readable key from the dashboard.                         |
| `experience_name` | `str \| None`   | Optional display name.                                         |
| `variation_id`    | `str`           | Internal id of the bucketed variation.                         |
| `variation_key`   | `str`           | Human-readable variation key.                                  |
| `variation_name`  | `str \| None`   | Optional display name.                                         |
| `bucket_value`    | `int`           | The 0–9999 bucket value that selected this variation.          |

### `FeatureResult`

Returned by `Context.run_feature()` (single) and `Context.run_features()`
(list). Carries resolved variables and the backing experience attribution.

| Field             | Type                  | Description                                              |
| ----------------- | --------------------- | -------------------------------------------------------- |
| `feature_id`      | `str`                 | Internal config id of the feature.                       |
| `feature_key`     | `str`                 | Human-readable feature key.                              |
| `feature_name`    | `str \| None`         | Optional display name.                                   |
| `status`          | `FeatureStatus`       | `ENABLED` or `DISABLED`.                                 |
| `variables`       | `Mapping[str, Any]`   | Type-cast feature variables (immutable mapping).         |
| `experience_id`   | `str \| None`         | Backing experience id, if any.                           |
| `experience_key`  | `str \| None`         | Backing experience key.                                  |
| `experience_name` | `str \| None`         | Backing experience name.                                 |
| `variation_id`    | `str \| None`         | Backing variation id.                                    |
| `variation_key`   | `str \| None`         | Backing variation key.                                   |

### `ConversionEvent`

A single typed conversion event produced by `Context.track_conversion()`.
Used internally by the tracking queue and exposed to consumers via
`ConversionResult.events`.

| Field             | Type                       | Description                                       |
| ----------------- | -------------------------- | ------------------------------------------------- |
| `visitor_id`      | `str`                      | Visitor identifier.                               |
| `goal_id`         | `str`                      | Internal config id of the goal.                   |
| `goal_key`        | `str`                      | Human-readable goal key.                          |
| `goal_name`       | `str \| None`              | Optional display name.                            |
| `account_id`      | `str \| None`              | Sourced from the config snapshot.                 |
| `project_id`      | `str \| None`              | Sourced from the config snapshot.                 |
| `conversion_data` | `Mapping[str, Any]`        | Revenue / metadata payload (immutable).           |
| `bucketing_data`  | `Mapping[str, str]`        | `{experience_id: variation_id}` attribution.      |
| `event_type`      | `str`                      | Always `"conversion"`.                            |

### `ConversionResult`

Returned by `Context.track_conversion()`.

| Field                  | Type                              | Description                                                                |
| ---------------------- | --------------------------------- | -------------------------------------------------------------------------- |
| `events`               | `tuple[ConversionEvent, ...]`     | Typed events queued for delivery.                                          |
| `duplicate_prevented`  | `bool`                            | `True` when deduplication suppressed the event.                            |
| `queued_event_count`   | `int`                             | Number of events that entered the queue.                                   |
| `event` (property)     | `ConversionEvent \| None`         | The most-useful single event (revenue/data event when present, else base). |

When `conversion_data` is supplied the SDK creates **two** events per
conversion: a base conversion event (no data) for goal attribution, and
a revenue/data event carrying the `conversion_data`. Both share the same
`goal_id` and `event_type="conversion"` — the distinction lives in the
presence of `goalData` on the wire payload.

### `TrackingFlushResult`

Returned by `Context.release_queues()`.

| Field                    | Type           | Description                                                    |
| ------------------------ | -------------- | -------------------------------------------------------------- |
| `attempted`              | `bool`         | `False` if the queue was empty (no POST was made).             |
| `delivered_event_count`  | `int`          | Total events delivered across all batches.                     |
| `delivered_batch_count`  | `int`          | Number of HTTP POSTs made.                                     |
| `remaining_event_count`  | `int`          | Events still queued (non-zero on partial failure).             |
| `reason`                 | `str \| None`  | The string passed to `release_queues(reason=...)`.             |

### `ExperienceDiagnostic`

Returned by `Context.diagnose_experience()`. A non-exception version of
`run_experience()` that carries *why* the visitor was not bucketed.

| Field             | Type                          | Description                                                                  |
| ----------------- | ----------------------------- | ---------------------------------------------------------------------------- |
| `experience_key`  | `str`                         | Requested experience key.                                                    |
| `resolved`        | `bool`                        | `True` if a variation was bucketed.                                          |
| `reason`          | `str`                         | Reason code (`"resolved"`, `"audience_miss"`, `"location_miss"`, etc.).      |
| `message`         | `str`                         | Human-readable explanation.                                                  |
| `result`          | `ExperienceResult \| None`    | The matched variation, when `resolved=True`.                                 |
| `details`         | `Mapping[str, Any]`           | Immutable diagnostic metadata (bucket value, traffic allocation, etc.).      |

### `FeatureDiagnostic`

Returned by `Context.diagnose_feature()`.

| Field         | Type                       | Description                                                  |
| ------------- | -------------------------- | ------------------------------------------------------------ |
| `feature_key` | `str`                      | Requested feature key.                                       |
| `resolved`    | `bool`                     | `True` when a feature decision was produced.                 |
| `reason`      | `str`                      | Reason code (`"resolved"`, `"feature_disabled"`, etc.).      |
| `message`     | `str`                      | Human-readable explanation.                                  |
| `result`      | `FeatureResult \| None`    | The resolved feature, when `resolved=True`.                  |
| `details`     | `Mapping[str, Any]`        | Immutable diagnostic metadata.                               |

### `GoalDiagnostic`

Returned by `Context.diagnose_goal()`. Use it to check goal availability
without raising `GoalNotFoundError`.

| Field      | Type                  | Description                                                    |
| ---------- | --------------------- | -------------------------------------------------------------- |
| `goal_key` | `str`                 | Requested goal key.                                            |
| `resolved` | `bool`                | `True` when the goal exists in the current snapshot.           |
| `reason`   | `str`                 | `"resolved"` or `"goal_not_found"`.                            |
| `message`  | `str`                 | Human-readable explanation.                                    |
| `details`  | `Mapping[str, Any]`   | Immutable diagnostic metadata (e.g. `available_goal_count`).   |

### `EntityDiagnostic`

Returned by `Context.diagnose_config_entity()` and
`Context.diagnose_config_entity_by_id()`.

| Field         | Type                  | Description                                                            |
| ------------- | --------------------- | ---------------------------------------------------------------------- |
| `entity_type` | `str`                 | `"experiences"`, `"features"`, `"goals"`, `"audiences"`, etc.          |
| `lookup`      | `str`                 | `"key"` or `"id"`.                                                     |
| `value`       | `str`                 | The key or id that was looked up.                                      |
| `resolved`    | `bool`                | `True` when the entity was found.                                      |
| `reason`      | `str`                 | `"resolved"` or `"not_found"`.                                         |
| `message`     | `str`                 | Human-readable explanation.                                            |
| `details`     | `Mapping[str, Any]`   | Immutable diagnostic metadata.                                         |

### `LifecycleEventPayload`

Delivered to every handler subscribed via `Core.on(...)`.

| Field         | Type                       | Description                                            |
| ------------- | -------------------------- | ------------------------------------------------------ |
| `event`       | `LifecycleEvent`           | The enum value of the event (see below).               |
| `details`     | `Mapping[str, Any]`        | Privacy-safe event-specific details (immutable).       |
| `occurred_at` | `datetime`                 | UTC timestamp of the emission.                         |

Visitor ids inside `details` are replaced with a 16-character SHA-256
prefix (`visitor_ref`); sensitive keys are redacted.

### `RefresherStatus`

Returned by `Core.refresher_status` (a property). Use it for health
checks and operational metrics around the optional config refresher.

| Field                   | Type                  | Description                                                          |
| ----------------------- | --------------------- | -------------------------------------------------------------------- |
| `enabled`               | `bool`                | `False` when `SDKConfig.refresh` is `None`.                          |
| `is_running`            | `bool`                | `False` after stop, fork, terminal failure, or worker crash.         |
| `consecutive_failures`  | `int`                 | Resets to `0` on every success/skip.                                 |
| `last_refresh_at`       | `float \| None`       | POSIX time of the last attempt.                                      |
| `last_success_at`       | `float \| None`       | POSIX time of the last refresh that produced or matched a snapshot.  |
| `last_error_type`       | `str \| None`         | Class name of the last failure exception.                            |
| `last_error_at`         | `float \| None`       | POSIX time of the last failure.                                      |
| `forked_in_child`       | `bool`                | `True` after the SDK detects an `os.fork()` in this process.         |
| `terminal_failure`      | `bool`                | `True` after a terminal-failure shutdown.                            |

## Enums

### `FeatureStatus`

The status of a resolved `FeatureResult`. Inherits from `str` so the
underlying value is JSON-serializable.

| Member     | Value         |
| ---------- | ------------- |
| `ENABLED`  | `"enabled"`   |
| `DISABLED` | `"disabled"`  |

```python
from convert_sdk import FeatureStatus

if feature.status == FeatureStatus.ENABLED:
    ...
```

### `LifecycleEvent`

Names the lifecycle events `Core` can emit.

| Member                       | Value                          | Fires when                                              |
| ---------------------------- | ------------------------------ | ------------------------------------------------------- |
| `CONFIG_UPDATED`             | `"config_updated"`             | Background refresh produced a new snapshot.             |
| `CONVERSION_CREATED`         | `"conversion_created"`         | Conversion built (before enqueue).                      |
| `CONVERSION_DEDUPLICATED`    | `"conversion_deduplicated"`    | Dedup blocked a duplicate conversion.                   |
| `TRACKING_EVENT_QUEUED`      | `"tracking_event_queued"`      | Events added to the queue.                              |
| `QUEUE_RELEASE_STARTED`      | `"queue_release_started"`      | `release_queues()` began draining a non-empty queue.    |
| `QUEUE_RELEASED`             | `"queue_released"`             | All batches delivered successfully.                     |
| `TRACKING_DELIVERY_FAILED`   | `"tracking_delivery_failed"`   | HTTP transport error interrupted delivery.              |

```python
from convert_sdk import LifecycleEvent

core.on(LifecycleEvent.QUEUE_RELEASED, handler)
```

## Errors

All SDK errors derive from `ConvertSDKError`, which carries `.code` (a
short string identifier) and `.context` (a privacy-safe immutable
mapping with structured diagnostic data).

| Error                       | Base                  | Raised when                                                                 |
| --------------------------- | --------------------- | --------------------------------------------------------------------------- |
| `ConvertSDKError`           | `Exception`           | Base class for every SDK error.                                             |
| `InitializationError`       | `ConvertSDKError`     | Base for initialization and readiness failures.                             |
| `ConfigValidationError`     | `InitializationError` | Configuration input is malformed or incomplete.                             |
| `ConfigLoadError`           | `InitializationError` | Remote configuration fetch failed.                                          |
| `TrackingError`             | `ConvertSDKError`     | Base for conversion-tracking failures.                                      |
| `GoalNotFoundError`         | `TrackingError`       | `track_conversion()` called with a goal absent from the config snapshot.    |
| `ConversionDataError`       | `TrackingError`       | `conversion_data` contains invalid types (e.g. `bool`, `dict`, `bytes`).    |
| `TrackingDeliveryError`     | `TrackingError`       | `release_queues()` failed mid-flush. Carries partial-success bookkeeping.   |

Example usage:

```python
from convert_sdk import ConfigLoadError, GoalNotFoundError

try:
    core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
except ConfigLoadError as exc:
    logger.error("convert config fetch failed: %s %s", exc.code, exc.context)

try:
    context.track_conversion("unknown")
except GoalNotFoundError as exc:
    logger.warning("missing goal: %s context=%s", exc.code, dict(exc.context))
```

`TrackingDeliveryError` carries extra attributes (`delivered_event_count`,
`delivered_batch_count`, `remaining_event_count`) on the exception itself
so callers can recover without parsing `.context`. The underlying
transport exception is available via `__cause__`.

## Protocols (extension types)

These are structural `Protocol`s, not classes — implement them with any
class that matches the method signatures (no subclassing required).

| Protocol      | Purpose                                                    | Default implementation       |
| ------------- | ---------------------------------------------------------- | ---------------------------- |
| `Transport`   | Fetch config and POST tracking events.                     | `HttpxTransport` (built-in)  |
| `DataStore`   | Persist visitor state and goal-dedup records.              | `InMemoryDataStore`          |
| `EventBus`    | Dispatch lifecycle events to subscribed handlers.          | (in-memory event bus)        |

See [Code Examples](python-code-examples.md#persistent-datastore) for an
end-to-end `DataStore` implementation.

## Next steps

- [Code Examples](python-code-examples.md) — usage patterns for every
  return type
- [Segments Manager](python-segments-manager.md) — segment-specific APIs
- [Configuration Options](python-configuration.md) — config dataclasses
