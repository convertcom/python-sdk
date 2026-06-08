# Initialization

`Core` is the SDK entry point. You construct it with an `SDKConfig`, then call
`initialize()`. An `SDKConfig` must carry **exactly one** config source:

- `data` — a preloaded config dict. Initialization makes **no network call**.
  Ideal for local development, tests, and environments that load config out of
  band.
- `sdk_key` — the SDK fetches config over HTTPS through the built-in transport.

Both forms return a ready `Core` from `initialize()`.

> The runnable samples below import `SAMPLE_CONFIG` from the docs fixture
> (`tests/docs_sample_config.py`). In your own code, substitute your real
> config dict or your `sdk_key`.

## Direct config (offline, no network)

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
assert core.is_ready

context = core.create_context("visitor-001")
result = context.run_experience("checkout-experiment")
assert result is None or result.variation_key in {"control", "treatment"}

core.close()
```

Direct-config initialization is fully synchronous and touches no network, so it
is safe to use in unit tests and offline tooling.

## `sdk_key` (fetch config over HTTPS)

Read the key from the environment — **never hard-code credentials**:

```python
import os
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()
context = core.create_context("visitor-001")
```

`sdk_key` initialization fetches config over HTTPS through the built-in
`httpx`-backed transport. Configure the endpoint, timeout, and TLS behavior
through `TransportConfig` on `SDKConfig.transport`. A non-HTTPS base URL is
rejected at construction time (NFR8: TLS-only transport).

You can also target a non-default `environment` or a low-cache config route:

```python
import os
from convert_sdk import Core, SDKConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        environment="staging",
        cache_level="low",
    )
).initialize()
```

## The context-manager lifecycle

`Core` is a context manager, so it releases transport resources cleanly even if
an error is raised:

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

with Core(SDKConfig(data=SAMPLE_CONFIG)).initialize() as core:
    context = core.create_context("visitor-001")
    result = context.run_experience("checkout-experiment")
# Queued tracking is flushed and transport resources are released on exit.
```

## Public API this guide relies on

- `convert_sdk.Core` — entry point; `Core(config, *, transport=...)`,
  `.initialize()`, `.is_ready`, `.create_context(...)`, `.close()`, context
  manager
- `convert_sdk.SDKConfig` — `data` | `sdk_key`, `environment`, `cache_level`,
  `transport`, `batch_size`, `auto_flush_interval_ms`, `data_store`, `logger`
- `convert_sdk.TransportConfig` — `base_url`, `timeout`, `auth_secret`,
  `headers`, `verify_tls`
