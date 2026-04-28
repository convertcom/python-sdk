# Initialization

The SDK entry point is `Core`. You pass an `SDKConfig` at construction time; the
config is loaded synchronously during `__init__`. Once `core.is_ready` is `True`,
you can create visitor contexts.

Relevant source files:

- [`src/convert_sdk/core.py`](../src/convert_sdk/core.py) — `Core`
- [`src/convert_sdk/config.py`](../src/convert_sdk/config.py) — `SDKConfig`,
  `TransportConfig`, `TrackingConfig`

## SDK key mode

Use `sdk_key` when you want the SDK to fetch the project config from the Convert
CDN at startup. The fetch is synchronous and blocking; network failures raise
`ConfigLoadError`.

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

The `sdk_key_secret`, if present, is sent as a `Bearer` token in the `Authorization`
header when fetching config and delivering tracking events.

## Direct config mode

Use `config_data` when you want to supply the project config yourself — from a
file, a cache, or an inline dict. No network call is made. This mode is ideal for
tests, CI, and local development.

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

## SDKConfig fields

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `sdk_key` | `str \| None` | `None` | Convert project SDK key |
| `sdk_key_secret` | `str \| None` | `None` | Optional HMAC secret for authorization |
| `config_data` | `Mapping \| None` | `None` | Inline config payload (overrides network fetch) |
| `environment` | `str \| None` | `None` | Environment filter applied to experience eligibility |
| `transport` | `TransportConfig` | see below | Network settings for config-fetch and tracking |
| `tracking` | `TrackingConfig` | see below | Queue settings for conversion delivery |

Exactly one of `sdk_key` or `config_data` must be provided; passing neither raises
`ConfigValidationError`.

## TransportConfig fields

| Field | Default | Purpose |
|-------|---------|---------|
| `config_endpoint` | `https://cdn-4.convertexperiments.com/api/v1` | Base URL for config-fetch |
| `tracking_endpoint` | `https://metrics.convertexperiments.com/v1` | Base URL for tracking delivery |
| `headers` | `{}` | Extra HTTP headers appended to every request |
| `timeout_seconds` | `5.0` | Per-request timeout |
| `verify_tls` | `True` | Whether to verify TLS certificates |

## TrackingConfig fields

| Field | Default | Purpose |
|-------|---------|---------|
| `batch_size` | `10` | Maximum events per tracking POST |
| `source` | `"python-sdk"` | `source` field in tracking payload |
| `enrich_data` | `True` | Whether to set `enrichData: true` in tracking payload |

## Environment filter

When `environment` is set, the SDK only activates experiences that list that
environment string in their `environments` array in the config. Pass the same
environment string you set in the Convert dashboard.

## Error types raised during initialization

| Error | When raised |
|-------|-------------|
| `ConfigValidationError` | Neither `sdk_key` nor `config_data` was provided, or the payload shape is invalid |
| `ConfigLoadError` | Network or HTTP error while fetching config with `sdk_key` |
| `InitializationError` | Base class; also raised if `visitor_id` is empty in `create_context()` |

All three are importable from `convert_sdk`. They share a common base
`ConvertSDKError` with `.code` and `.context` attributes for structured error
handling:

```python
from convert_sdk import ConfigLoadError

try:
    core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"]))
except ConfigLoadError as exc:
    print(exc.code, exc.context)
```

## Reusing Core across requests

`Core` is designed to be a long-lived singleton. Create one instance at
application startup and reuse it. The `TrackingQueue` owned by `Core` is
thread-safe (protected by a `threading.Lock`), so `Core` is safe to share across
threads (Django, Gunicorn workers running in the same process) and across async
tasks.

```python
# application startup
core = Core(SDKConfig(config_data=project_config))

# per-request handler
def handle_request(visitor_id: str) -> None:
    context = core.create_context(visitor_id)
    result = context.run_experience("checkout-flow")
    ...
```

## What to read next

- [Evaluation](evaluation.md) — create a `Context` and run decisions
- [Tracking](tracking.md) — record conversions after decisions
- [Extending](extending.md) — swap the transport or data store
