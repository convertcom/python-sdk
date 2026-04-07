## convert-python-sdk

This repository currently contains the Story 1.1 scaffold for Convert's Python SDK.

Canonical package decisions frozen in this story:

- Distribution name: `convert-python-sdk`
- Import package: `convert_sdk`
- Stable public imports: `Core`, `Context`, and `__version__`

The scaffold is intentionally minimal. Feature initialization, configuration loading, local evaluation, and tracking behavior will land in later stories.

### Local Development

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --group dev
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
UV_CACHE_DIR=/tmp/uv-cache uv build
```

### Public Import Boundary

```python
from convert_sdk import Context, Core, __version__
```
