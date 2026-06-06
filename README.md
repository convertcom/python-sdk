# Convert Python SDK

The Convert Experiences FullStack SDK for Python — server-side A/B testing,
feature flags, and personalizations for Python 3.9+ applications (Django,
Flask, FastAPI, and plain Python services).

> **Status:** Foundation scaffold (Story 1.1). This release freezes the
> packaging foundation and the public import boundary. Initialization,
> evaluation, and tracking behavior land in subsequent stories.

## Installation

```bash
pip install convert-python-sdk
```

The distribution name on PyPI is `convert-python-sdk`; the import package is
`convert_sdk`. The two differ by design — the hyphenated name is the
discoverability surface on PyPI, the snake_case name is the ergonomic import
path.

## Usage

```python
from convert_sdk import Core, Context, __version__

print(__version__)  # "0.1.0"
```

`Core` and `Context` are placeholders in this release; they exist to freeze the
public import boundary so later stories can implement behavior without renaming
the public surface.

## Compatibility

- Python 3.9+
- No required web framework
- No JavaScript runtime dependency
- Zero runtime dependencies in this release

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
