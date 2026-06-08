# Convert Python SDK

The Convert Experiences FullStack SDK for Python — server-side A/B testing,
feature flags, and personalizations for Python 3.9+ applications (Django,
Flask, FastAPI, and plain Python services).

The SDK is framework-agnostic and sync-first: you can reach your first
experiment value in plain Python, with no web framework and — using direct
config — no network call.

## Installation

```bash
pip install convert-python-sdk
```

- **Distribution name (PyPI):** `convert-python-sdk`
- **Import package:** `convert_sdk`

The two differ by design — the hyphenated name is the discoverability surface on
PyPI, the snake_case name is the ergonomic import path.

**Compatibility**

- Python 3.9+
- No required web framework
- No JavaScript runtime dependency
- One runtime dependency (`httpx`), used only for `sdk_key` initialization

## Quickstart

The fastest path to a first successful run uses **direct config** — a preloaded
config payload, no network call:

```python
from convert_sdk import Core, SDKConfig

config_data = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [
        {
            "id": "e1",
            "key": "checkout-experiment",
            "variations": [
                {"id": "v1", "key": "control", "traffic_allocation": 50.0},
                {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
            ],
        }
    ],
}

# Initialize from direct config — ready immediately, no network.
core = Core(SDKConfig(data=config_data)).initialize()

# Create a visitor-scoped context.
context = core.create_context("visitor-001")

# Evaluate an experience.
result = context.run_experience("checkout-experiment")
if result is not None:
    print("Bucketed into:", result.variation_key)

core.close()
```

## Initialization

`Core` is the entry point. Construct it with an `SDKConfig`, then call
`initialize()`. Provide **exactly one** of `data` (direct config) or `sdk_key`
(remote config).

### Direct config (offline, no network)

```python
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(data=config_data)).initialize()
assert core.is_ready
```

Direct-config initialization makes no network call and is ideal for local
development, tests, and environments that load config out of band.

### `sdk_key` (fetch config over HTTPS)

```python
import os
from convert_sdk import Core, SDKConfig

# Read the key from the environment — never hard-code credentials.
core = Core(SDKConfig(sdk_key=os.environ["CONVERT_SDK_KEY"])).initialize()
```

`sdk_key` initialization fetches config over HTTPS through the built-in
transport. Inject the key from an environment variable or your secret store;
do not embed real keys in source.

`Core` is also a context manager, so it releases transport resources cleanly:

```python
with Core(SDKConfig(data=config_data)).initialize() as core:
    context = core.create_context("visitor-001")
    ...
```

## Creating a visitor context

`create_context` binds a visitor identity (and optional visitor attributes) to
the current immutable config snapshot:

```python
context = core.create_context(
    "visitor-001",
    visitor_attributes={"country": "US", "plan": "pro"},
)
```

Visitor attributes are used for audience qualification. They are copied
defensively — later mutations to the dict you pass never affect the context.
Keep and reuse the returned `context` to evaluate the same visitor repeatedly;
the SDK does not cache contexts for you.

## Experience evaluation

`run_experience` evaluates a single experience for the visitor. It returns a
typed `ExperienceResult` when the visitor qualifies and buckets into a
variation, or `None` for any normal miss (missing experience, unqualified
visitor, no active variation). It never raises for normal outcomes and performs
no network I/O.

```python
result = context.run_experience("checkout-experiment")
if result is not None:
    print(result.experience_key, result.variation_key, result.variation_id)

# Evaluate all applicable experiences at once:
for result in context.run_experiences():
    print(result.experience_key, "->", result.variation_key)
```

You can overlay request-time attributes for a single call without mutating the
stored context:

```python
result = context.run_experience(
    "checkout-experiment",
    attributes={"country": "DE"},
)
```

## Feature evaluation

`run_feature` resolves a feature flag and its typed variables for the visitor.
It reads the feature change from the visitor's selected variation and casts each
variable using the feature's declared types. It returns a typed `FeatureResult`
when the feature is enabled for the visitor, or `None` for a normal miss
(undeclared, unavailable, or disabled feature). It never raises for normal
outcomes and performs no network I/O.

```python
feature = context.run_feature("checkout-banner")
if feature is not None:
    print(feature.status.value)          # "enabled"
    print(feature.variables["enabled"])  # typed per the feature definition (bool)
    print(feature.variables["headline"]) # str

# Resolve all applicable features:
for feature in context.run_features():
    print(feature.feature_key, feature.variables)
```

## Conversion tracking

`track_conversion` records a goal conversion for the visitor. It is lightweight
and synchronous — it deduplicates by `(visitor_id, goal_id)` and appends to an
in-process batch queue. **No network call happens on `track_conversion`**;
queued events are delivered when the queue is released via `core.flush()`,
batch-size release (`SDKConfig.batch_size`, default `10`), an opt-in periodic
timer, or a best-effort `atexit` hook.

```python
result = context.track_conversion("purchase_completed", revenue=49.99)
print(result.tracked, result.reason)   # True None

# A default duplicate for the same (visitor, goal) is suppressed:
again = context.track_conversion("purchase_completed")
print(again.tracked, again.reason)      # False "deduplicated"

# force_multiple re-tracks (e.g. repeated revenue/transactions):
context.track_conversion("purchase_completed", revenue=10.0, force_multiple=True)

# Deliver queued events explicitly (the canonical control point):
core.flush()
```

## Runtime Integration

Choosing *when* to flush depends on your runtime (Lambda, Cloud Run, gunicorn,
uvicorn, Celery, CLI). The default lifecycle is **explicit-flush-only**, which is
safe everywhere. See **[`docs/runtime-integration.md`](docs/runtime-integration.md)**
for a per-runtime decision table and copy-pasteable flush snippets, including the
opt-in daemonic periodic timer (`SDKConfig.auto_flush_interval_ms`), the
best-effort `atexit` hook, and the documented SIGTERM pattern.

## Runnable examples

Self-contained, framework-agnostic examples live in [`examples/`](examples/) and
run locally with no external services:

```bash
python examples/direct_config.py      # direct-config initialization
python examples/basic_experience.py   # bucket a visitor into a variation
python examples/basic_feature.py      # resolve a feature and read typed variables
```

They share a small sample config (`examples/_sample_config.py`) and read any
`sdk_key` from the `CONVERT_SDK_KEY` environment variable rather than embedding
credentials.

## Documentation

The advanced guides live under [`docs/`](docs/index.md) — start at the
[documentation index](docs/index.md). Highlights:

- **Topic guides:** [Initialization](docs/initialization.md),
  [Evaluation](docs/evaluation.md), [Tracking](docs/tracking.md),
  [Queue control](docs/queue-control.md), [Debugging](docs/debugging.md),
  [Extending](docs/extending.md), [Support workflows](docs/support-workflows.md),
  [Runtime integration](docs/runtime-integration.md)
- **Migration guides:** [Migrating from raw REST](docs/migration-from-rest.md),
  [Migrating from the JavaScript SDK](docs/migration-from-javascript.md)

Every code sample in those guides is executed against the current public API by
the test suite, so the documentation cannot drift from the implementation.

## Public API

Importable from `convert_sdk`:

- `Core`, `Context`
- `SDKConfig`, `TransportConfig`
- `ExperienceResult`, `FeatureResult`, `FeatureStatus`
- `ConversionResult`, `ConversionStatus`
- error types: `ConvertSDKError`, `ConfigError`, `InvalidConfigError`,
  `ConfigLoadError`, `TransportError`, `TrackingDeliveryError`
- `__version__`

## Development

This project uses [uv](https://docs.astral.sh/uv/) and the `hatchling` build
backend.

```bash
# Install dev tooling
uv sync --group dev

# Run the test suite
uv run pytest

# Build wheel and sdist
uv build
```

## License

Apache-2.0
