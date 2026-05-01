# Configuration Options

`SDKConfig` is the single configuration object passed to `Core(...)`. It
carries every setting the SDK needs: credentials, environment filter,
network behaviour, tracking-queue behaviour, and optional background
config refresh.

All four config dataclasses are **frozen** (immutable) — construct them
fresh; never mutate fields after the fact.

## Configuration Object

```python
from convert_sdk import (
    Core,
    SDKConfig,
    TrackingConfig,
    TransportConfig,
    RefreshConfig,
)

core = Core(
    SDKConfig(
        sdk_key="YOUR_SDK_KEY",
        sdk_key_secret="OPTIONAL_HMAC_SECRET",
        environment="production",
        config_data=None,                       # or supply an inline payload
        transport=TransportConfig(
            config_endpoint="https://cdn-4.convertexperiments.com/api/v1",
            tracking_endpoint="https://metrics.convertexperiments.com/v1",
            headers={},
            timeout_seconds=5.0,
            verify_tls=True,
        ),
        tracking=TrackingConfig(
            batch_size=10,
            source="python-sdk",
            enrich_data=True,
        ),
        refresh=RefreshConfig(
            interval_seconds=300.0,
            jitter_seconds=30.0,
            backoff_initial_seconds=30.0,
            backoff_max_seconds=600.0,
            backoff_factor=2.0,
            on_terminal_failure=None,
        ),
    )
)
```

## Field reference

### SDKConfig

| Field             | Type                       | Default                  | Purpose                                                                 |
| ----------------- | -------------------------- | ------------------------ | ----------------------------------------------------------------------- |
| `sdk_key`         | `str \| None`              | `None`                   | Convert project SDK key. Required unless `config_data` is supplied.     |
| `sdk_key_secret`  | `str \| None`              | `None`                   | Optional HMAC secret. Sent as a `Bearer` token on config + tracking.    |
| `config_data`     | `Mapping[str, Any] \| None`| `None`                   | Inline project payload. When set, no network fetch is made.             |
| `environment`     | `str \| None`              | `None`                   | Environment filter applied to experience eligibility.                   |
| `transport`       | `TransportConfig`          | `TransportConfig()`      | Endpoints, headers, timeouts, TLS verification.                         |
| `tracking`        | `TrackingConfig`           | `TrackingConfig()`       | Conversion queue behaviour.                                             |
| `refresh`         | `RefreshConfig \| None`    | `None`                   | Opt-in background config refresh. `None` runs zero background threads.  |

Exactly one of `sdk_key` or `config_data` must be provided; passing
neither raises `ConfigValidationError`.

### TransportConfig

| Field               | Type                       | Default                                              | Purpose                                                  |
| ------------------- | -------------------------- | ---------------------------------------------------- | -------------------------------------------------------- |
| `config_endpoint`   | `str`                      | `https://cdn-4.convertexperiments.com/api/v1`        | Base URL for config fetch.                               |
| `tracking_endpoint` | `str`                      | `https://metrics.convertexperiments.com/v1`          | Base URL for tracking delivery.                          |
| `headers`           | `Mapping[str, str]`        | `{}`                                                 | Extra HTTP headers appended to every SDK request.        |
| `timeout_seconds`   | `float`                    | `5.0`                                                | Per-request timeout for the bundled `httpx` transport.   |
| `verify_tls`        | `bool`                     | `True`                                               | Whether to verify TLS certificates.                      |

To swap the entire transport (e.g. for async HTTP, mTLS, or stubbing in
tests), pass a custom `Transport` implementation to `Core(SDKConfig(...),
transport=my_transport)` instead of editing `TransportConfig`. See the
[Code Examples](python-code-examples.md#persistent-datastore) page.

### TrackingConfig

| Field           | Type   | Default        | Purpose                                                         |
| --------------- | ------ | -------------- | --------------------------------------------------------------- |
| `batch_size`    | `int`  | `10`           | Maximum events per tracking POST. Larger queues split into N.   |
| `source`        | `str`  | `"python-sdk"` | The `source` field written to every outgoing tracking payload.  |
| `enrich_data`   | `bool` | `True`         | Sets `enrichData: true` in the tracking payload.                |

### RefreshConfig

`RefreshConfig` is **opt-in**. The default `SDKConfig.refresh = None`
runs zero background threads — behaviour is byte-for-byte identical to
not having a refresher at all.

| Field                       | Type                                | Default      | Purpose                                                             |
| --------------------------- | ----------------------------------- | ------------ | ------------------------------------------------------------------- |
| `interval_seconds`          | `float`                             | `300.0`      | Time between successful refresh attempts.                           |
| `jitter_seconds`            | `float`                             | `30.0`       | Random ± jitter applied to each interval to spread fleet ticks.     |
| `backoff_initial_seconds`   | `float`                             | `30.0`       | First failure waits this long before retrying.                      |
| `backoff_max_seconds`       | `float`                             | `600.0`      | Cap on retry delay (must be strictly greater than initial).         |
| `backoff_factor`            | `float`                             | `2.0`        | Exponential growth factor (must be strictly greater than 1.0).      |
| `on_terminal_failure`       | `Callable[[Exception], None] \| None` | `None`     | Optional callback fired once when the refresher stops permanently.  |

`RefreshConfig.__post_init__` rejects misconfigurations at construction
with `ConfigValidationError`:

- `interval_seconds >= 1.0`
- `0 <= jitter_seconds <= interval_seconds`
- `backoff_initial_seconds > 0`
- `backoff_max_seconds > backoff_initial_seconds`
- `backoff_factor > 1.0`

`RefreshConfig` requires an `sdk_key`-initialised `Core`; in direct-config
mode the worker is not started (logged as `refresh.skipped` with reason
`direct_config_no_remote_endpoint`).

## Project Data Structure

When you use `config_data` (direct-config mode) you supply the raw
project payload yourself. The shape mirrors the response from the
Convert config CDN — see the shared
[Data Model Reference](how-convert-works) for the full schema. A minimal
empty project looks like:

```python
{
    "account_id": "1001",
    "project": {"id": "2002", "name": "Demo"},
    "experiences": [],
    "features": [],
    "goals": [],
}
```

In production, set `sdk_key` and let the SDK fetch the payload from the
CDN; reserve `config_data` for tests and offline development.

## Environment filter

When `SDKConfig.environment` is set, the SDK only activates experiences
that list that environment string in their `environments` array in the
config. Use the same string you set in the Convert dashboard
(`"production"`, `"staging"`, etc.). When `environment` is `None`, no
filter is applied.

## Next steps

- [Initialization](python-initialization.md) — how config is loaded and
  validated
- [Code Examples](python-code-examples.md) — applied configuration in
  context
- [Return Types & DTOs](python-return-types.md) — typed shapes the SDK
  returns
