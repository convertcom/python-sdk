# Convert Python SDK — Documentation

Advanced guides for the Convert Experiences FullStack SDK for Python. If you are
just getting started, read the [README quickstart](../README.md) first — it
takes you to a first bucketed variation in plain Python with no network call.
These guides go deeper into each surface and into migrating from other
integrations.

All code samples in these guides are executed against the current public API by
`tests/test_docs_samples.py`, so they cannot drift from the implemented SDK.

## Topic guides

| Guide | What it covers |
|-------|----------------|
| [Initialization](initialization.md) | `Core` + `SDKConfig`, `sdk_key` (remote) vs `data` (direct/offline), the context-manager lifecycle, reading keys from the environment. |
| [Evaluation](evaluation.md) | `run_experience` / `run_experiences`, `run_feature` / `run_features`, typed results, request-time attribute overlays, default and custom segments. |
| [Tracking](tracking.md) | `track_conversion`, deduplication by `(visitor, goal)`, `revenue`, `force_multiple`, the typed `ConversionResult`. |
| [Queue control](queue-control.md) | `flush()`, `batch_size`, the opt-in periodic timer, the `atexit` hook, and the `LifecycleEvent.API_QUEUE_RELEASED` signal via `Core.on`. |
| [Debugging](debugging.md) | The cross-SDK diagnostic surface: `diagnose_experience` / `diagnose_feature` / `diagnose_goal` / `diagnose_entity`, the closed `DiagnosticReason` vocabulary, and the redaction-safe log seam. |
| [Extending](extending.md) | The `@runtime_checkable` extension Protocols (transport, storage, event bus), how to inject your own implementations, and where the seams are. |
| [Support workflows](support-workflows.md) | Using diagnostics and lifecycle events to triage support questions and keep parity coverage current. |
| [Runtime integration](runtime-integration.md) | Per-runtime flush patterns (Lambda, Cloud Run, gunicorn, uvicorn, Celery, CLI). |

## Migration guides

| Guide | Audience |
|-------|----------|
| [Migrating from raw REST](migration-from-rest.md) | Teams calling the Convert config and tracking endpoints directly today. |
| [Migrating from the JavaScript SDK](migration-from-javascript.md) | Teams who know the JS FullStack SDK and want the Pythonic mental model. |

## The public API at a glance

Everything the guides reference is importable from `convert_sdk`:

- Entry points: `Core`, `Context`
- Config: `SDKConfig`, `TransportConfig`
- Typed results: `ExperienceResult`, `FeatureResult`, `FeatureStatus`,
  `ConversionResult`, `ConversionStatus`, `CustomSegmentsResult`
- Diagnostics: `DiagnosticReason`, `ExperienceDiagnostic`, `FeatureDiagnostic`,
  `GoalDiagnostic`, `EntityDiagnostic`
- Lifecycle: `LifecycleEvent`
- Extension seams: `DataStore` (and the `InMemoryDataStore` default)
- Errors: `ConvertSDKError`, `ConfigError`, `InvalidConfigError`,
  `ConfigLoadError`, `TransportError`, `TrackingDeliveryError`
