# Convert Python SDK

`convert-python-sdk` is a framework-agnostic Python SDK for local Convert experience and feature evaluation in backend code.

### Installation

```bash
pip install convert-python-sdk
```

Requirements:

- Python `>=3.9`
- No Django, Flask, FastAPI, or JavaScript runtime dependency in the core package

### Public API

```python
from convert_sdk import Core, SDKConfig
```

Primary concepts:

- `Core` initializes the SDK and owns the current immutable config snapshot
- `Context` is a reusable visitor-scoped object created from `Core`
- `run_experience()` and `run_feature()` evaluate locally without request-time network calls

### Initialize With An SDK Key

Use `sdk_key` when you want the SDK to fetch config from Convert over HTTPS.

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
        ),
    )
)

assert core.is_ready
```

### Initialize With Direct Config

Use direct config for local development, tests, and first-run onboarding without a network dependency.

```python
from convert_sdk import Core, SDKConfig

project_config = {
    "account_id": "1001",
    "project": {"id": "2002", "name": "Demo"},
    "features": [],
    "experiences": [],
}

core = Core(
    SDKConfig(
        config_data=project_config,
        environment="production",
    )
)

assert core.is_ready
```

### Create A Visitor Context

```python
context = core.create_context(
    "visitor-123",
    {"tier": "premium"},
)
```

The returned `Context` is reusable across multiple evaluations for the same visitor.

### Run An Experience

```python
result = context.run_experience(
    "checkout-flow",
    location_attributes={"path": "/checkout"},
)

if result is None:
    print("No experience result for this visitor")
else:
    print(result.experience_key, result.variation_key)
```

### Run A Feature

```python
feature = context.run_feature(
    "checkout-banner",
    location_attributes={"path": "/checkout"},
)

if feature is None:
    print("Feature unavailable for this visitor")
else:
    print(feature.status.value, feature.variables)
```

### Run All Applicable Decisions

```python
experience_results = context.run_experiences(
    location_attributes={"path": "/checkout"},
)
feature_results = context.run_features(
    location_attributes={"path": "/checkout"},
)
```

Normal no-match outcomes are non-exceptional:

- `run_experience(...) -> None`
- `run_feature(...) -> None`
- `run_experiences(...) -> []`
- `run_features(...) -> []`

### Examples

Runnable framework-agnostic examples are available in `examples/`:

- `examples/direct_config.py`
- `examples/basic_experience.py`
- `examples/basic_feature.py`

Run them with:

```bash
python examples/direct_config.py
python examples/basic_experience.py
python examples/basic_feature.py
```

### Local Development

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --group dev
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -p no:cacheprovider
UV_CACHE_DIR=/tmp/uv-cache uv build
```
