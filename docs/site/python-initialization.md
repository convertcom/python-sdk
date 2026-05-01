# Initialization

The Convert Python SDK is initialized through `Core(SDKConfig(...))`. The
config is loaded synchronously during construction; once `core.is_ready`
returns `True`, you can create per-visitor contexts and run evaluations.

## Using SDK Key

Pass `sdk_key` (and optionally `sdk_key_secret`) when you want the SDK to
fetch the project config from the Convert CDN at startup.

```python
import os

from convert_sdk import Core, SDKConfig, TransportConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        sdk_key_secret=os.getenv("CONVERT_SDK_KEY_SECRET"),
        environment="production",
        transport=TransportConfig(
            config_endpoint="https://cdn-4.convertexperiments.com/api/v1",
            timeout_seconds=5.0,
        ),
    )
)

assert core.is_ready
```

The fetch is **synchronous and blocking**. Network failures raise
`ConfigLoadError`; structurally invalid payloads raise
`ConfigValidationError`. Both are subclasses of `InitializationError` and
`ConvertSDKError`, so you can catch broadly when needed.

When `sdk_key_secret` is set, the SDK sends it as a `Bearer` token in the
`Authorization` header on both config fetch and tracking delivery.

## Readiness

The Python SDK does **not** expose an `onReady()` Promise. By the time
`Core(...)` returns, the config has already been loaded — there is no
async wait state to observe.

```python
core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
if core.is_ready:
    # Safe to call core.create_context(...)
    ...
```

If construction fails, the exception propagates and `core` is never
assigned. There is no half-initialized state.

## Using Static Configuration

For tests, CI, local development, or environments without internet access,
supply the config payload inline through `config_data`. No network call is
made.

```python
from convert_sdk import Core, SDKConfig

project_config = {
    "account_id": "1001",
    "project": {"id": "2002", "name": "Demo"},
    "features": [],
    "experiences": [],
    "goals": [],
}

core = Core(SDKConfig(config_data=project_config))

assert core.is_ready
```

Exactly one of `sdk_key` or `config_data` must be provided; passing
neither raises `ConfigValidationError`.

## Creating a User Context

Once `core.is_ready` is `True`, create a `Context` for each visitor.

```python
context = core.create_context(
    "visitor-abc123",
    {"tier": "premium", "country": "US", "device": "mobile"},
)
```

`Context` is a reusable per-visitor handle. Run as many evaluations on it
as you need within a single request; do not create a new context per
evaluation.

If `visitor_attributes` is supplied to `create_context()`, the stored
attributes for that visitor are **replaced** (not merged); only
`visitor_properties` and `default_segments` carry over from previously
stored state. To merge, omit the second argument and call
`context.update_visitor_attributes({...})` afterwards.

## Attributes Object

Visitor attributes are a plain `Mapping[str, Any]`. They drive audience
matching, custom-segment evaluation, and rule targeting. Common keys:

```python
{
    "country": "US",
    "language": "en",
    "device": "mobile",
    "tier": "premium",
    "logged_in": True,
}
```

There is no mandatory shape — provide whatever attributes your audiences
target on. Convert audiences match against attribute keys/values you
declare in the dashboard.

## Reusing Core across requests

`Core` is designed to be a long-lived singleton. Create one instance at
application startup and reuse it. The internal `TrackingQueue` is
`threading.Lock`-protected, so concurrent `track_conversion()` and
`release_queues()` calls from different threads are safe.

```python
# application startup
core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))


# per-request handler
def handle_request(visitor_id: str) -> None:
    context = core.create_context(visitor_id)
    result = context.run_experience("checkout-flow")
    ...
    context.release_queues(reason="end_of_request")
```

For graceful shutdown, call `core.close()` (or use `with Core(...) as
core:`). This stops the optional config refresher thread and releases the
HTTP client.

## Automatic config refresh (opt-in)

Long-running services can opt into background config refresh by setting
`SDKConfig.refresh`. The default `refresh=None` runs no background
threads.

```python
from convert_sdk import Core, RefreshConfig, SDKConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        refresh=RefreshConfig(
            interval_seconds=300.0,        # refresh every 5 minutes
            jitter_seconds=30.0,           # spread fleet ticks
            backoff_initial_seconds=30.0,
            backoff_factor=2.0,
            backoff_max_seconds=600.0,
        ),
    )
)
```

Each successful refresh that produces a different snapshot fires the
`LifecycleEvent.CONFIG_UPDATED` lifecycle event. Subscribe with
`core.on(LifecycleEvent.CONFIG_UPDATED, handler)`.

Manual refresh is also available:

```python
core.refresh_now()                        # fire-and-forget
ok = core.refresh_now(wait=True)          # block until next attempt finishes
ok = core.refresh_now(wait=True, timeout=10.0)
```

`RefreshConfig` requires an `sdk_key`-initialised `Core` (not direct
config), and rejects misconfigurations at construction with
`ConfigValidationError`. See
[Configuration Options](python-configuration.md#refreshconfig) for the
full field list.

## Initialization errors

| Error                    | When raised                                                    |
| ------------------------ | -------------------------------------------------------------- |
| `ConfigValidationError`  | Neither `sdk_key` nor `config_data` provided, or invalid shape |
| `ConfigLoadError`        | Network or HTTP error while fetching with `sdk_key`            |
| `InitializationError`    | Base class; raised for empty `visitor_id` in `create_context()` |

All three share a common base `ConvertSDKError` with `.code` and
`.context` attributes for structured handling.

```python
from convert_sdk import ConfigLoadError, Core, SDKConfig

try:
    core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
except ConfigLoadError as exc:
    print(exc.code, exc.context)
```

## Next steps

- [Configuration Options](python-configuration.md) — every field on
  `SDKConfig`, `TransportConfig`, `TrackingConfig`, `RefreshConfig`
- [Code Examples](python-code-examples.md) — running experiences,
  features, segments, conversions, queue control
- [Return Types & DTOs](python-return-types.md) — typed shapes returned
  by `run_experience`, `run_feature`, `track_conversion`, `release_queues`
