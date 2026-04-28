# Convert Python SDK — Documentation

This is the reference documentation for `convert-python-sdk`. The quickstart in
`README.md` covers installation and first run. The guides below cover advanced
usage, operational concerns, and migration from other integration styles.

## Topic guides

| Guide | What it covers |
|-------|----------------|
| [Initialization](initialization.md) | SDK key, direct config, transport and tracking options |
| [Evaluation](evaluation.md) | Experiences, features, segments, visitor attributes |
| [Tracking](tracking.md) | Conversion events, revenue data, deduplication, attribution |
| [Queue control](queue-control.md) | Explicit flush, batch sizing, lifecycle events |
| [Debugging](debugging.md) | Diagnostic logging, typed errors, `*Diagnostic` result objects |
| [Extending](extending.md) | Custom transport, storage, and event-bus via `SDKConfig` |
| [Support workflows](support-workflows.md) | What to gather before filing a bug, reading `reason` codes |

## Migration guides

| Guide | Audience |
|-------|----------|
| [Migrating from raw REST](migration-from-rest.md) | Teams currently calling the Convert config and tracking endpoints directly |
| [Migrating from the JavaScript SDK](migration-from-javascript.md) | Teams porting JS backend code or sharing mental models with a JS front end |

## Public API quick-reference

All symbols are importable from `convert_sdk`:

```python
from convert_sdk import (
    Core,
    SDKConfig,
    TrackingConfig,
    TransportConfig,
    Context,              # returned by Core.create_context()
    # --- result types ---
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
    ConversionResult,
    ConversionEvent,
    TrackingFlushResult,
    # --- diagnostic types ---
    ExperienceDiagnostic,
    FeatureDiagnostic,
    GoalDiagnostic,
    EntityDiagnostic,
    # --- error types ---
    ConfigLoadError,
    ConfigValidationError,
    ConversionDataError,
    GoalNotFoundError,
    InitializationError,
    TrackingError,
    # --- lifecycle events ---
    LifecycleEvent,
    LifecycleEventPayload,
    # --- extension ports ---
    DataStore,
    InMemoryDataStore,
)
```

See [`src/convert_sdk/__init__.py`](../src/convert_sdk/__init__.py) for the
canonical export list.
