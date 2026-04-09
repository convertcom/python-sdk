from importlib.metadata import distribution
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_distribution_metadata_matches_story_contract() -> None:
    dist = distribution("convert-python-sdk")
    requirements = dist.requires or []

    assert dist.metadata["Name"] == "convert-python-sdk"
    assert dist.metadata["Requires-Python"] == ">=3.9"
    assert any(requirement.startswith("httpx") for requirement in requirements)
    assert all(
        forbidden not in requirement.lower()
        for forbidden in ("django", "flask", "fastapi")
        for requirement in requirements
    )


def test_pyproject_freezes_convert_sdk_package_boundary() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'packages = ["src/convert_sdk"]' in pyproject
    assert '"examples/**/*.py"' in pyproject
    assert '"src/convert_sdk/py.typed" = "convert_sdk/py.typed"' in pyproject
