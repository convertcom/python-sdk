# Migrating from Raw REST

This guide is for teams currently calling the Convert config and tracking
endpoints directly (plain HTTP with `requests`, `httpx`, `curl`, etc.) and
wanting to migrate to the SDK.

## What changes

| Concern | Raw REST | SDK |
|---------|----------|-----|
| Config fetch | HTTP GET on startup (or per-request) | Done once in `Core(SDKConfig(...))` |
| Bucketing | Implemented manually or not at all | Deterministic in-process, no request-time network call |
| Audience rules | Evaluated on the Convert platform | Evaluated locally from config snapshot |
| Conversion POST | Manual JSON construction and POST | `context.track_conversion()` + `context.release_queues()` |
| Batching | Manual or absent | Automatic batching with configurable `batch_size` |
| Deduplication | Manual per-visitor tracking | Built-in `(visitor_id, goal_id)` dedup via `DataStore` |
| Retries | Manual | Re-call `release_queues()` after a transport failure |

## Side-by-side: config fetch

**Raw REST:**

```python
import os
import httpx

sdk_key = os.environ["CONVERT_SDK_KEY"]
response = httpx.get(
    f"https://cdn-4.convertexperiments.com/api/v1/config/{sdk_key}",
    params={"environment": "production"},
    headers={"Accept": "application/json"},
)
response.raise_for_status()
project_config = response.json()
```

**SDK equivalent:**

```python
import os
from convert_sdk import Core, SDKConfig, TransportConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        environment="production",
        transport=TransportConfig(
            config_endpoint="https://cdn-4.convertexperiments.com/api/v1",
        ),
    )
)
# core._snapshot holds the parsed config; no manual JSON parsing needed
```

## Side-by-side: bucketing

**Raw REST (manual bucketing):**

```python
import mmh3

def bucket_visitor(experience_id, visitor_id, seed=9999):
    hash_input = f"{experience_id}{visitor_id}"
    hash_value = mmh3.hash(hash_input, seed) & 0xFFFFFFFF
    return int((hash_value / 4294967296) * 10000)

def select_variation(variations, bucket_value):
    accumulated = 0
    for variation in variations:
        accumulated += variation["traffic_allocation"]
        if bucket_value < accumulated:
            return variation["id"]
    return None

experience = next(
    e for e in project_config["experiences"] if e["key"] == "checkout-flow"
)
bucket = bucket_visitor(experience["id"], "visitor-abc123")
variation_id = select_variation(experience["variations"], bucket)
```

**SDK equivalent:**

```python
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(config_data=project_config))
context = core.create_context("visitor-abc123", {"tier": "premium"})

result = context.run_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

if result is not None:
    variation_id = result.variation_id
    bucket_value = result.bucket_value  # same value as the manual algorithm above
```

The SDK's `bucket_value` matches the value a correct manual MurmurHash3
implementation would produce for the same inputs.

## Side-by-side: tracking POST

**Raw REST:**

```python
import httpx, os

payload = {
    "source": "my-backend",
    "enrichData": True,
    "accountId": project_config["account_id"],
    "projectId": project_config["project"]["id"],
    "visitors": [
        {
            "visitorId": "visitor-abc123",
            "events": [
                {
                    "eventType": "conversion",
                    "data": {
                        "goalId": "goal-1",
                        "goalData": [{"key": "revenue", "value": 49.99}],
                        "bucketingData": {"exp-checkout": "var-treatment"},
                    },
                }
            ],
        }
    ],
}

sdk_key = os.environ["CONVERT_SDK_KEY"]
httpx.post(
    f"https://metrics.convertexperiments.com/v1/track/{sdk_key}",
    json=payload,
    headers={"Content-Type": "application/json"},
)
```

**SDK equivalent:**

```python
result = context.track_conversion(
    "purchase",
    conversion_data={"revenue": 49.99},
)
# events are queued; send them:
flush = context.release_queues(reason="end_of_request")
print(flush.delivered_event_count)
```

The SDK builds the payload automatically from the config snapshot. The
`bucketingData` field is populated by re-evaluating all active experiences at
the moment of `track_conversion()`.

## Operational improvements over raw REST

### Automatic bucketing with audience / location evaluation

Raw REST integrations typically send all visitors to Convert for server-side
bucketing or skip audience rules entirely. The SDK evaluates audience rules and
site-area (location) rules locally using the config snapshot, meaning:

- No extra network round-trip per request for bucketing decisions
- Audience rules are evaluated immediately, not deferred to the platform

### Batching

The SDK accumulates events and sends them in configurable batches (default: 10
events per POST). Raw REST integrations typically POST one event per HTTP request.

### Deduplication

The SDK prevents double-counting the same goal for the same visitor within a
process lifetime. Raw REST integrations must implement deduplication manually.

### Revenue attribution

When `conversion_data` is supplied, the SDK automatically creates a base
conversion event (for goal attribution) and a separate transaction event (for
revenue data). The base event is sent only once per `(visitor_id, goal_id)`
pair; transaction events can be repeated with `force_multiple_transactions=True`.

### Privacy-safe diagnostics

The SDK redacts visitor ids and SDK keys from all diagnostic logs. Raw REST
integrations log raw credentials and ids.

## Configuration you can reuse

If you already fetch the project config and parse it, you can pass it directly
to the SDK without changing your fetching logic:

```python
from convert_sdk import Core, SDKConfig

# your existing config fetch result
project_config = existing_fetch_function()

core = Core(SDKConfig(config_data=project_config, environment="production"))
```

See [Initialization](initialization.md) for the full `SDKConfig` reference.

## What to read next

- [Initialization](initialization.md) — SDK key and direct config options
- [Evaluation](evaluation.md) — how the SDK replaces manual bucketing
- [Tracking](tracking.md) — conversion payload details and dedup rules
- [Queue control](queue-control.md) — flushing and batching configuration
