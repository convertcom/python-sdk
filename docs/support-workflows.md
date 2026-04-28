# Support Workflows

This guide describes what diagnostic information to collect before filing a bug
report and how to read the `reason` codes emitted by the SDK.

Relevant source files:

- [`src/convert_sdk/diagnostics.py`](../src/convert_sdk/diagnostics.py)
- [`src/convert_sdk/errors.py`](../src/convert_sdk/errors.py)
- [`src/convert_sdk/domain/results.py`](../src/convert_sdk/domain/results.py)

## Before filing a bug

Collect the following before opening an issue:

1. **SDK version** — `python -c "import convert_sdk; print(convert_sdk.__version__)"`
2. **Python version** — `python --version`
3. **Initialization mode** — SDK key or direct config?
4. **Diagnostic log output** — Enable debug logging (see below) and capture the
   output for the failing request.
5. **Diagnostic result** — For evaluation or tracking failures, use the
   `diagnose_*` methods and include the full `reason`, `message`, and `details`
   fields.
6. **Error details** — If an exception was raised, include `exc.code` and
   `dict(exc.context)`.
7. **Privacy note** — Raw visitor ids and SDK keys are automatically redacted in
   diagnostic logs; do not manually re-add them to your bug report.

## Enabling diagnostic logging

```python
import logging
import sys

logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(message)s",
)
logging.getLogger("convert_sdk.diagnostics").setLevel(logging.DEBUG)
logging.getLogger("convert_sdk.tracking").setLevel(logging.DEBUG)
```

The logger names are:

| Logger name | Content |
|-------------|---------|
| `convert_sdk.diagnostics` | Evaluation, bucketing, and tracking lifecycle events |
| `convert_sdk.tracking` | Delivery warnings when HTTP transport fails |

## Reading experience `reason` codes

| `reason` | What it means | What to check |
|----------|---------------|---------------|
| `bucketed` | Visitor is bucketed — this is a success | Variation key is in `result` |
| `experience_not_found` | Key typo or experience not in config | Verify experience key in dashboard |
| `experience_inactive` | Experience status is not `active` | Check experience status in dashboard |
| `environment_miss` | Environment filter excludes this experience | Check `environment` in `SDKConfig` and the experience's `environments` list |
| `audience_miss` | Visitor attributes did not satisfy the audience | Print `visitor_attributes` and compare to audience rules |
| `location_miss` | Location attributes did not match the site-area | Print `location_attributes` and compare to site-area rules |
| `outside_traffic` | Bucket value is above total allocated traffic | Check `traffic_allocation` sum in variations; verify `bucket_value` in `details` |
| `all_variations_excluded` | All variations are paused or excluded | Check variation statuses in dashboard |

## Reading feature `reason` codes

Feature evaluation backs every feature lookup through an experience. The `reason`
codes are the same as the experience codes above, plus:

| `reason` | What it means |
|----------|---------------|
| `feature_not_found` | Key typo or feature not in config |
| `no_backing_experience` | Feature exists but no experience references it |

## Using `diagnose_*` for structured investigation

The `diagnose_*` methods return the full decision record without raising. Use them
in place of `run_*` when debugging:

```python
diag = context.diagnose_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)
print("resolved:", diag.resolved)
print("reason:", diag.reason)
print("message:", diag.message)
print("details:", dict(diag.details))
# details may include: bucket_value, audience_key, variation_key, etc.
```

For goal lookup failures:

```python
goal_diag = context.diagnose_goal("purchase")
print("resolved:", goal_diag.resolved)
print("reason:", goal_diag.reason)
print("available_goal_count:", goal_diag.details.get("available_goal_count"))
```

For generic entity lookups (useful when verifying config was loaded correctly):

```python
entity = context.diagnose_config_entity("experience", "checkout-flow")
print("resolved:", entity.resolved)
print("reason:", entity.reason)
```

## Checking initialization health

```python
from convert_sdk import Core, SDKConfig, ConfigLoadError

try:
    core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
except ConfigLoadError as exc:
    print("code:", exc.code)
    print("context:", dict(exc.context))

print("is_ready:", core.is_ready)
snapshot = core.snapshot
print("experiences:", len(snapshot.experiences_by_key))
print("features:", len(snapshot.features_by_key))
print("goals:", len(snapshot.goals_by_key))
```

If `core.is_ready` is `True` but entity counts are zero, the config was loaded
but is empty — check whether the correct environment was requested.

## Verifying bucketing parity

To verify that a visitor/experience pair produces the same bucket value as the
JavaScript SDK:

```python
from convert_sdk.evaluation.bucketing import get_bucket_value

bucket = get_bucket_value(
    visitor_id="visitor-abc123",
    experience_id="exp-checkout",
)
print("bucket_value:", bucket)  # compare to JS SDK output
```

The Python SDK uses a pure-Python MurmurHash3 32-bit implementation with seed
`9999`. The hash input is always `f"{experience_id}{visitor_id}"` (experience id
first). The JavaScript SDK uses the same algorithm and input order.

## Tracking delivery failures

If events are not appearing in the Convert dashboard:

1. Check `flush_result.remaining_event_count` — non-zero means delivery was
   interrupted.
2. Subscribe to `LifecycleEvent.TRACKING_DELIVERY_FAILED` to capture the
   `error_type` (see [Queue control](queue-control.md)).
3. Confirm that `release_queues()` is called before the process exits or the
   request completes.
4. Confirm that `sdk_key` or `account_id`/`project_id` is present in the config
   snapshot — the transport requires at least one routing identifier.

## Minimum reproduction

When filing a bug, include a minimal standalone script that reproduces the issue
using direct config mode (no network dependency):

```python
import os

from convert_sdk import Core, SDKConfig

config = {
    "account_id": "YOUR_ACCOUNT_ID",
    "project": {"id": "YOUR_PROJECT_ID", "name": "Repro"},
    "experiences": [
        # paste the minimal experience definition from your config
    ],
    "features": [],
    "goals": [],
}

core = Core(SDKConfig(config_data=config))
context = core.create_context("repro-visitor-1", {"tier": "premium"})
diag = context.diagnose_experience("your-experience-key")
print(diag.resolved, diag.reason, dict(diag.details))
```

Using `config_data` instead of `sdk_key` avoids network dependencies and
confidential key exposure in bug reports.
