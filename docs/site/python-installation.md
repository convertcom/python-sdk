# Installation

The Convert Python SDK is published to PyPI as `convert-python-sdk`.

- **Repository:** https://github.com/convertcom/python-sdk
- **Package:** https://pypi.org/project/convert-python-sdk/
- **Import name:** `convert_sdk`

## Requirements

| Requirement       | Version                                         |
| ----------------- | ----------------------------------------------- |
| Python            | `>=3.9`                                         |
| HTTP client       | [`httpx`](https://www.python-httpx.org/) (bundled) |
| Framework         | None — no Django, Flask, FastAPI, or JS runtime dependency in the core package |

The core distribution stays framework-free. Framework-specific helper
packages (Django, FastAPI, Flask) are planned for a later phase and ship
as separate distributions; they are not part of `convert-python-sdk`.

## Install with pip

```bash
pip install convert-python-sdk
```

## Install with uv

```bash
uv pip install convert-python-sdk
```

## Install with Poetry

```bash
poetry add convert-python-sdk
```

## Install with PDM

```bash
pdm add convert-python-sdk
```

## Pinning a version

Pin to a specific minor version in production. The SDK follows
[Semantic Versioning](https://semver.org/) — minor releases stay backwards
compatible within `0.x`.

```bash
pip install "convert-python-sdk>=0.1,<0.2"
```

## Importing the SDK

Every public symbol is importable from the top-level `convert_sdk` package.

```python
from convert_sdk import (
    Core,
    SDKConfig,
    TrackingConfig,
    TransportConfig,
    RefreshConfig,
    Context,
    # Result types
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
    ConversionResult,
    ConversionEvent,
    TrackingFlushResult,
    # Diagnostic types
    ExperienceDiagnostic,
    FeatureDiagnostic,
    GoalDiagnostic,
    EntityDiagnostic,
    # Errors
    ConvertSDKError,
    ConfigLoadError,
    ConfigValidationError,
    ConversionDataError,
    GoalNotFoundError,
    InitializationError,
    TrackingError,
    TrackingDeliveryError,
    # Lifecycle events
    LifecycleEvent,
    LifecycleEventPayload,
    # Extension ports
    DataStore,
    EventBus,
    Transport,
    InMemoryDataStore,
)
```

## Verifying the install

```python
import convert_sdk

print(convert_sdk.__version__)
```

## Type checking

The package ships an inline `py.typed` marker — types are visible to
`mypy`, `pyright`, and `pylance` without any extra stubs install.

## Next steps

- [Python Quickstart](python-quickstart.md) — full working example
- [Initialization](python-initialization.md) — SDK key and direct-config
  initialization
- [Configuration Options](python-configuration.md) — full field reference
