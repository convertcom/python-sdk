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

## Automatic config refresh (opt-in)

> **Post-MVP (architecture Phase 2), FR31.** Off by default. Omitting `refresh`
> (or passing `refresh=None`) preserves MVP behavior byte-for-byte: **no daemon
> thread, no refresh events, no added cost.**

A long-running service can opt into background config refresh by supplying a
`RefreshConfig` on `SDKConfig.refresh`. When enabled for a remote (`sdk_key`)
instance, the SDK starts one **daemon thread** that periodically re-fetches
config through the *same* transport used at init and **atomically swaps** the
immutable snapshot in place. In-flight evaluations always see a single coherent
snapshot — the swap is mutex-guarded (see
[`docs/adr/0001-config-refresh-concurrency-and-backoff.md`](adr/0001-config-refresh-concurrency-and-backoff.md)).

```python
from convert_sdk import Core, RefreshConfig, SDKConfig, TransportConfig

config = SDKConfig(
    sdk_key="your-sdk-key-here",  # remote mode is required for refresh
    transport=TransportConfig(base_url="https://cdn-4.convertexperiments.com"),
    refresh=RefreshConfig(
        interval_seconds=300.0,     # base poll period (default: 5 minutes)
        jitter_seconds=30.0,        # +U(0, jitter) per cycle, avoids thundering herd
        backoff_factor=2.0,         # exponential backoff on transient failures
        backoff_max_seconds=600.0,  # backoff ceiling (never tight-loops)
    ),
)
core = Core(config).initialize()
# ... long-running service ...
core.refresh_now()   # optional: trigger an out-of-band refresh immediately
core.close()         # stops the daemon refresh thread
```

### Policy fields

| Field | Default | Meaning |
|-------|---------|---------|
| `interval_seconds` | `300.0` | Base period between successful refreshes. Must be `> 0`. |
| `jitter_seconds` | `30.0` | Max uniform random jitter added per cycle. Must be `0 <= jitter <= interval`. |
| `backoff_factor` | `2.0` | Exponential multiplier applied per consecutive failure. Must be `>= 1.0`. |
| `backoff_max_seconds` | `600.0` | Ceiling on the backed-off wait. Must be `>= interval`. |

A misconfigured policy (e.g. `interval_seconds <= 0`, `jitter > interval`) raises
`InvalidConfigError` at `RefreshConfig` construction.

### Failure handling

A background refresh that fails (network error, non-2xx, malformed config) **does
not** disturb the running SDK: the previous good snapshot keeps serving and the
host process never crashes. Each failure is logged through the diagnostic logger
(Story 4.1) as a `refresh.fail` record, and once the exponential backoff reaches
`backoff_max_seconds` the typed Story 4.2 error is surfaced through the logger so
operators can see a persistently failing endpoint without an exception escaping
into a request path.

### `CONFIG_UPDATED` lifecycle event

On every successful swap the SDK emits `LifecycleEvent.CONFIG_UPDATED` on the
event bus, carrying the new `account_id`, `project_id`, and per-type
`entity_counts`. Subscribe to bust any caches you derive from config:

```python
from convert_sdk import LifecycleEvent

core.on(LifecycleEvent.CONFIG_UPDATED, lambda payload, _err: my_cache.clear())
```

### Long-lived `Context` semantics

A `Context` retains whatever snapshot was current **when it was created**. This
gives a request a coherent view for its full duration even if a refresh fires
mid-request; create a fresh context (per request) to pick up the latest config.

### Threading / process model

- One refresh worker per `Core`; it is a **daemon thread** and never blocks
  interpreter exit.
- Refresh is **process-local** (NFR9) — there is no cross-process coordination.
- **Do not** rely on refresh surviving a `fork()` without `exec()`: the daemon
  thread is not duplicated into the child. In pre-fork servers (Gunicorn,
  Celery prefork) **re-initialize the SDK in each worker process** after fork.
- Supplying a `RefreshConfig` in **direct-config** (`data`) mode starts no worker
  — there is no remote endpoint to poll — and the SDK emits a `refresh.skipped`
  diagnostic rather than silently ignoring the misconfiguration.

## Public API this guide relies on

- `convert_sdk.Core` — entry point; `Core(config, *, transport=...)`,
  `.initialize()`, `.is_ready`, `.create_context(...)`, `.refresh_now()`,
  `.close()`, context manager
- `convert_sdk.SDKConfig` — `data` | `sdk_key`, `environment`, `cache_level`,
  `transport`, `batch_size`, `auto_flush_interval_ms`, `data_store`, `logger`,
  `refresh`
- `convert_sdk.RefreshConfig` — `interval_seconds`, `jitter_seconds`,
  `backoff_factor`, `backoff_max_seconds` (opt-in automatic refresh, FR31)
- `convert_sdk.TransportConfig` — `base_url`, `timeout`, `auth_secret`,
  `headers`, `verify_tls`
