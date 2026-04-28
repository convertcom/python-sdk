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
protected by a `threading.Lock`, so concurrent `track_conversion()` and
`release_queues()` calls from different threads will not corrupt the queue.

Caveat: `Core.create_context()` performs an unlocked
`load_context_state` → `save_context_state` round-trip against the configured
`DataStore`. With the default `InMemoryDataStore`, two threads calling
`create_context()` for the *same* `visitor_id` at the same time can race and
overwrite each other's stored state. If you create contexts concurrently for
the same visitor (uncommon — most apps create one context per request), wrap
`create_context()` in your own lock or supply a `DataStore` that serialises
read-modify-write internally.

```python
# application startup
core = Core(SDKConfig(config_data=project_config))

# per-request handler
def handle_request(visitor_id: str) -> None:
    context = core.create_context(visitor_id)
    result = context.run_experience("checkout-flow")
    ...
```

## Automatic config refresh (opt-in)

Long-running services can opt into background config refresh by passing a
`RefreshConfig` to `SDKConfig.refresh`. Without a `RefreshConfig`, no
background activity runs and behaviour is identical to the MVP — the
default is `refresh=None`.

```python
from convert_sdk import Core, SDKConfig
from convert_sdk.config import RefreshConfig

core = Core(
    SDKConfig(
        sdk_key=os.environ["CONVERT_SDK_KEY"],
        sdk_key_secret=os.getenv("CONVERT_SDK_KEY_SECRET"),
        environment="production",
        refresh=RefreshConfig(
            interval_seconds=300.0,        # refresh every 5 minutes
            jitter_seconds=30.0,           # +/- 30s to avoid herding instances
            backoff_initial_seconds=30.0,  # first failure waits 30s before retry
            backoff_factor=2.0,            # exponential backoff
            backoff_max_seconds=600.0,     # cap retries at 10 minutes apart
        ),
    )
)
```

### Behaviour

- Refresh runs on a daemon thread inside `Core`. The thread starts at
  `Core(...)` time and stops at `core.close()` (or when the host process
  exits).
- Each successful refresh that produces a different snapshot replaces
  `core.snapshot` through a single attribute swap. In-flight evaluations
  see either the old or new snapshot, never a partial state.
- Refresh attempts produce diagnostic events on the
  `convert_sdk.diagnostics` logger:

  | Event                       | Meaning                                                                               |
  |-----------------------------|---------------------------------------------------------------------------------------|
  | `refresh.start`             | A refresh attempt is beginning.                                                       |
  | `refresh.success`           | Fetch succeeded and the snapshot changed.                                             |
  | `refresh.skipped`           | Fetch succeeded but the snapshot is unchanged (or skipped for another stated reason). |
  | `refresh.fail`              | Transient failure. Includes `consecutive_failures` and `at_terminal_backoff`.         |
  | `refresh.terminal_failure`  | Terminal condition (bad upstream payload or apply-callback bug). Worker stops.        |
  | `refresh.fork_detected`     | The refresher detected an `os.fork()` in a child process; the worker is dead there.   |
  | `refresh.worker_crashed`    | An unexpected exception escaped the worker loop's own handler. Worker exits.          |

- Each successful refresh that produces a different snapshot also fires
  the `LifecycleEvent.CONFIG_UPDATED` lifecycle event with `account_id`,
  `project_id`, and `entity_counts` details. Subscribe through
  `core.on(LifecycleEvent.CONFIG_UPDATED, handler)` — this is the Python
  analog of the JavaScript SDK's `SystemEvents.CONFIG_UPDATED`. The
  `TrackingQueue`'s `account_id` and `project_id` are also refreshed so
  conversions queued after a refresh attribute to the new project.

### Failure handling

- **Transient transport failures** back off exponentially up to
  `backoff_max_seconds` and retry; the worker keeps retrying because
  silently freezing on stale config is worse than periodic retries.
  `on_terminal_failure` fires once per failure once the consecutive-
  failure count reaches the backoff cap.
- **Terminal failures** stop the worker. Two conditions count as terminal:
  (a) the upstream returned a structurally invalid payload
  (`ConfigValidationError`) — retrying the same broken response is
  futile; (b) the SDK's internal apply step raised, which indicates a
  programmer bug rather than a transient condition. In both cases
  `on_terminal_failure` fires once and the daemon thread exits;
  `core.refresher_status.is_running` flips to `False` and
  `terminal_failure` to `True`. Recovery requires recreating `Core`.
- `RefreshConfig.on_terminal_failure` is optional. Use it to surface a
  typed alert through your application's logger or metrics pipeline.
  Exceptions raised inside the callback are caught and logged on
  `convert_sdk.refresh`; they never crash the worker.
- Background failures **never** raise into the host process. The
  worker thread is daemon-mode, so it does not block process exit.

### Validation rules for `RefreshConfig`

`RefreshConfig.__post_init__` rejects misconfigurations at construction
time so the worker is never started in a degenerate state:

- `interval_seconds > 0`
- `0 ≤ jitter_seconds ≤ interval_seconds`
- `backoff_initial_seconds > 0`
- `backoff_max_seconds > backoff_initial_seconds` (strict — equality
  would fire the terminal callback on the very first failure)
- `backoff_factor > 1.0` (strict — factor=1.0 would mean the backoff
  cap is unreachable, so the terminal callback could never fire)

Invalid policies raise `ConfigValidationError` with a `code` of
`refresh.invalid_interval`, `refresh.invalid_jitter`, or
`refresh.invalid_backoff`.

### Long-lived `Context` objects and refresh

Refreshes update `core.snapshot` for new contexts. Existing `Context`
objects retain whatever snapshot was current when they were created;
this is intentional — a `Context` represents a coherent view of the
project for the duration of a request or unit of work.

If you need a long-lived `Context` to pick up refreshed config, recreate
it through `core.create_context(...)` after the refresh has happened.

### Process model expectations

- One refresher per `Core` instance. Spawning multiple `Core` objects
  spawns multiple refresher threads.
- Auto-refresh under `os.fork()` without `exec` is **not** supported.
  The forked child inherits a stopped daemon thread; recreate `Core`
  in the child process. This matches the broader expectation that SDK
  state stays process-local (NFR9).
- `Core.close()` and the context-manager form
  (`with Core(...) as core:`) stop the refresher cleanly. Use one of
  these for graceful shutdown. Process exit alone is fine — daemon
  threads do not block exit.

### Manual refresh

Call `core.refresh_now()` to wake the worker and trigger an attempt
immediately, regardless of the configured interval:

```python
core.refresh_now()                       # fire-and-forget
ok = core.refresh_now(wait=True)         # block until the next attempt finishes
ok = core.refresh_now(wait=True, timeout=10.0)  # custom timeout in seconds
```

`wait=True` returns `True` if the next refresh attempt completed
(success, snapshot-unchanged skip, transient failure, or terminal
failure) within `timeout` seconds, and `False` if it timed out. With
refresh disabled (`SDKConfig.refresh=None`) `refresh_now()` is a no-op
and returns `True`.

### Refresher observability

`core.refresher_status` returns a `RefresherStatus` snapshot for use in
operational metrics, health checks, or readiness probes:

```python
status = core.refresher_status
status.enabled              # False when SDKConfig.refresh is None
status.is_running           # False after stop, fork, terminal failure, or crash
status.consecutive_failures # 0 on success/skip; resets on success
status.last_refresh_at      # POSIX time of the last attempt (or None)
status.last_success_at      # POSIX time of the last refresh that produced or matched a snapshot
status.last_error_type      # exception class name of the last failure (or None)
status.last_error_at        # POSIX time of the last failure (or None)
status.forked_in_child      # True after the SDK detects an os.fork() in this process
status.terminal_failure     # True after a terminal-failure shutdown
```

### Direct-config mode

If `SDKConfig.config_data` is set (direct-config mode), there is no
remote endpoint to refresh from. Setting `refresh=RefreshConfig(...)`
in this mode logs a `refresh.skipped` diagnostic with
`reason=direct_config_no_remote_endpoint` and the worker is not
started. To pick up new config in direct-config mode, recreate `Core`.

## What to read next

- [Evaluation](evaluation.md) — create a `Context` and run decisions
- [Tracking](tracking.md) — record conversions after decisions
- [Extending](extending.md) — swap the transport or data store
