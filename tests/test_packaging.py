"""Packaging-contract tests for the Convert Python SDK (Story 1.1).

Verifies the py.typed marker ships, the distribution metadata matches the
frozen canonical naming, runtime dependencies stay empty, and the supported
Python floor is 3.9.
"""

import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _load_pyproject():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_py_typed_marker_present():
    """PEP 561 marker must exist so type information ships with the package."""
    marker = PROJECT_ROOT / "src" / "convert_sdk" / "py.typed"
    assert marker.is_file(), "src/convert_sdk/py.typed marker is missing"


def test_distribution_name_is_canonical():
    """Distribution name is the frozen canonical value convert-python-sdk."""
    project = _load_pyproject()["project"]
    assert project["name"] == "convert-python-sdk"


def test_runtime_dependency_is_httpx_with_compatible_bounds():
    """Story 1.2 adds httpx as the SDK's only runtime dependency, declared with
    compatible-release bounds (>=0.28,<1.0) and never an exact pin (qs-09 F-060).
    """
    project = _load_pyproject()["project"]
    deps = project.get("dependencies", [])
    assert deps == ["httpx>=0.28,<1.0"], (
        f"expected exactly the httpx compatible-release bound, got {deps}"
    )
    # No exact pins (== / ===) belong in pyproject runtime deps — those live
    # only in the CI lower-bounds override file (Story 5.1).
    for dep in deps:
        assert "==" not in dep, f"exact pin in runtime deps: {dep!r}"


def test_requires_python_floor_is_39():
    """The package must declare support for Python >=3.9."""
    project = _load_pyproject()["project"]
    assert project["requires-python"] == ">=3.9"


def test_installed_metadata_matches_when_available():
    """When installed, importlib.metadata must report the canonical name and
    version. Skips gracefully if the package is not installed in the env."""
    try:
        dist = importlib_metadata.distribution("convert-python-sdk")
    except importlib_metadata.PackageNotFoundError:
        import pytest

        pytest.skip("convert-python-sdk not installed in this environment")
    assert dist.metadata["Name"] == "convert-python-sdk"
    assert dist.version == "0.1.0"
