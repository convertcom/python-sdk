# Debugging

The SDK exposes three complementary debugging mechanisms: structured diagnostic
logging, typed errors with `.code` and `.context` attributes, and
`*Diagnostic` result objects that describe evaluation decisions without raising.

Relevant source files:

- [`src/convert_sdk/diagnostics.py`](../src/convert_sdk/diagnostics.py) —
  `log_diagnostic_event()`, `redact_diagnostic_details()`
- [`src/convert_sdk/errors.py`](../src/convert_sdk/errors.py) — error hierarchy
- [`src/convert_sdk/domain/results.py`](../src/convert_sdk/domain/results.py) —
  `ExperienceDiagnostic`, `FeatureDiagnostic`, `GoalDiagnostic`, `EntityDiagnostic`

## Diagnostic logging

All internal SDK activity emits structured `DEBUG`-level log records through the
Python `logging` module on the logger named `convert_sdk.diagnostics`.

Enable diagnostic output by setting that logger to `DEBUG`:

```python
import logging

logging.getLogger("convert_sdk.diagnostics").setLevel(logging.DEBUG)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)s %(message)s %(extra)s",  # adjust to your formatter
)
```

Or in Django `settings.py`:

```python
LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "convert_sdk.diagnostics": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
```

### Diagnostic log record structure

Each record has two `extra` fields:

| Field | Description |
|-------|-------------|
| `sdk_event` | Dot-separated event name, e.g. `evaluation.experience.completed` |
| `sdk_details` | Redacted dict of event-specific fields |

### Privacy redaction

Diagnostic logs never emit raw visitor ids, SDK keys, secrets, cookies, or raw
attribute mappings. Sensitive values are replaced with `"<redacted>"`. Visitor
ids are replaced with a 16-character SHA-256 prefix (`visitor_ref`).

The full list of redacted key patterns is in
[`src/convert_sdk/diagnostics.py`](../src/convert_sdk/diagnostics.py) under
`SENSITIVE_KEY_PARTS`.

### Key diagnostic events

| sdk_event | Fired by | Useful fields |
|-----------|----------|---------------|
| `sdk.initialization.started` | `Core.__init__` | `source`, `transport_type` |
| `sdk.initialization.succeeded` | `Core.__init__` | `is_ready`, `entity_counts` |
| `sdk.initialization.failed` | `Core.__init__` | `error_type`, `error_code` |
| `context.created` | `Core.create_context` | `had_existing_state`, `supplied_visitor_attribute_count` |
| `evaluation.experience.completed` | `Context.run_experience` | `matched`, `reason`, `variation_key`, `bucket_value` |
| `evaluation.feature.completed` | `Context.run_feature` | `matched`, `reason`, `status` |
| `evaluation.custom_segments.completed` | `Context.run_custom_segments` | `matched_segment_count` |
| `tracking.conversion.started` | `Context.track_conversion` | `has_conversion_data` |
| `tracking.conversion.queued` | `Context.track_conversion` | `event_count`, `queued_event_count` |
| `tracking.conversion.deduplicated` | `Context.track_conversion` | `reason` |
| `tracking.queue.release.started` | `release_queues` | `pending_event_count`, `batch_size` |
| `tracking.queue.release.succeeded` | `release_queues` | `delivered_event_count` |
| `tracking.delivery.failed` | `release_queues` | `error_type`, `remaining_event_count` |
| `lookup.goal.completed` | `Context.diagnose_goal` | `resolved`, `reason` |
| `lookup.entity.completed` | `Context.diagnose_config_entity` | `entity_type`, `resolved` |

## Typed errors

All SDK errors derive from `ConvertSDKError` and carry structured metadata:

```python
class ConvertSDKError(Exception):
    code: str | None        # machine-readable error code
    context: Mapping[str, Any]  # structured metadata (immutable)
```

### Error hierarchy

```
ConvertSDKError
├── InitializationError
│   ├── ConfigValidationError  (code: "config.validation_error")
│   └── ConfigLoadError        (code: "config.load_error")
└── TrackingError
    ├── GoalNotFoundError      (code: "goal.not_found")
    └── ConversionDataError    (code: "conversion.data_error")
```

Example structured error handling:

```python
from convert_sdk import GoalNotFoundError, ConfigLoadError

try:
    context.track_conversion("unknown-goal")
except GoalNotFoundError as exc:
    print(exc.code)                              # "goal.not_found"
    print(exc.context["goal_key"])               # "unknown-goal"
    print(exc.context["available_goal_count"])   # how many goals exist
```

## Diagnostic result objects

Instead of calling `run_experience()` (which returns `ExperienceResult | None`),
call `diagnose_experience()` to get the full decision record without raising:

```python
diag = context.diagnose_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

print(diag.resolved)     # bool — True when bucketed
print(diag.reason)       # str — why decision was made
print(diag.message)      # human-readable description
print(diag.result)       # ExperienceResult | None
print(diag.details)      # Mapping with bucket_value, etc.
```

The same pattern applies to features and goals:

```python
feat_diag = context.diagnose_feature("checkout-banner")
goal_diag = context.diagnose_goal("purchase")
entity_diag = context.diagnose_config_entity("experience", "checkout-flow")
entity_by_id = context.diagnose_config_entity_by_id("experience", "exp-checkout")
```

### ExperienceDiagnostic fields

| Field | Type | Description |
|-------|------|-------------|
| `experience_key` | `str` | The key requested |
| `resolved` | `bool` | Whether the visitor was bucketed |
| `reason` | `str` | Machine-readable reason code |
| `message` | `str` | Human-readable description |
| `result` | `ExperienceResult \| None` | Populated when `resolved=True` |
| `details` | `Mapping[str, Any]` | `bucket_value`, `audience_key`, etc. |

### FeatureDiagnostic fields

Same shape as `ExperienceDiagnostic`, with `feature_key` instead of
`experience_key` and an additional `experience_key` / `variation_key` in `details`.

### GoalDiagnostic fields

| Field | Type | Description |
|-------|------|-------------|
| `goal_key` | `str` | The key requested |
| `resolved` | `bool` | Whether the goal exists in the snapshot |
| `reason` | `str` | `"resolved"` or `"goal_not_found"` |
| `message` | `str` | Human-readable description |
| `details` | `Mapping[str, Any]` | `entity_key`, `available_goal_count` |

### EntityDiagnostic fields

| Field | Type | Description |
|-------|------|-------------|
| `entity_type` | `str` | e.g. `"experience"`, `"feature"` |
| `lookup` | `str` | `"key"` or `"id"` |
| `value` | `str` | The key or id that was looked up |
| `resolved` | `bool` | Whether the entity was found |
| `reason` | `str` | `"resolved"` or `"entity_not_found"` |
| `message` | `str` | Human-readable description |
| `details` | `Mapping[str, Any]` | `entity_type`, `lookup`, `value` |

## Experience `reason` codes

| `reason` | Meaning |
|----------|---------|
| `bucketed` | Visitor is in the experience and received a variation |
| `experience_not_found` | The experience key was not in the config snapshot |
| `experience_inactive` | Experience status is not `active` |
| `environment_miss` | The experience does not include the requested environment |
| `audience_miss` | Visitor attributes did not satisfy the audience rules |
| `location_miss` | Location attributes did not match the site-area rules |
| `outside_traffic` | Bucket value exceeded the total allocated traffic |
| `all_variations_excluded` | All variations have `status` set to exclude them |

## Cross-SDK comparable fields

The `ExperienceDiagnostic.details` dict always includes `bucket_value` when
bucketing was attempted. This value is deterministic across all Convert SDKs for
the same `(visitor_id, experience_id)` pair — you can compare the Python SDK's
`bucket_value` to the JavaScript SDK's bucketing output to verify parity.

The parity test suite at
[`tests/parity/`](../tests/parity/) exercises this contract with shared
test vectors.

## What to read next

- [Support workflows](support-workflows.md) — what to include in a bug report
- [Extending](extending.md) — replace the logger or transport for custom observability
- [Queue control](queue-control.md) — lifecycle events for delivery monitoring
