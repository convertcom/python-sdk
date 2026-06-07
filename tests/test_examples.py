"""Drift-protection tests for the quickstart examples and README (Story 1.6).

Lightweight coverage that keeps the onboarding path honest:

* Every advertised example file exists and is executable as a module.
* Running each example's callable against the offline sample config produces a
  real first-run outcome (a bucketed variation and a resolved, type-cast
  feature) — proving the documented first-run path actually works without a
  framework or network.
* The README is a real first-run guide (not the Story 1.1 scaffold) and only
  references the public API the SDK actually implements.

These tests are the executable guard against the README/examples drifting away
from the implemented public surface.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
README = PROJECT_ROOT / "README.md"

EXAMPLE_FILES = (
    "_sample_config.py",
    "direct_config.py",
    "basic_experience.py",
    "basic_feature.py",
)


def test_all_example_files_exist():
    assert EXAMPLES_DIR.is_dir(), "examples/ directory is missing"
    for name in EXAMPLE_FILES:
        assert (EXAMPLES_DIR / name).is_file(), f"missing example: examples/{name}"


def test_direct_config_example_runs_offline():
    module = importlib.import_module("examples.direct_config")
    summary = module.run()
    assert summary["ready"] is True
    assert summary["account_id"] == "100123"
    assert "checkout-experiment" in summary["experiences"]
    assert "checkout-banner" in summary["features"]


def test_basic_experience_example_buckets_a_variation():
    module = importlib.import_module("examples.basic_experience")
    summary = module.run("visitor-001")
    assert summary is not None, "example should bucket the sample visitor"
    assert summary["experience_key"] == "checkout-experiment"
    assert summary["variation_key"] in {"control", "treatment"}


def test_basic_feature_example_resolves_typed_variables():
    module = importlib.import_module("examples.basic_feature")
    summary = module.run("visitor-001")
    assert summary is not None, "example should resolve the sample feature"
    assert summary["feature_key"] == "checkout-banner"
    assert summary["status"] == "enabled"
    variables = summary["variables"]
    assert isinstance(variables["enabled"], bool)
    assert isinstance(variables["max_items"], int)
    assert isinstance(variables["headline"], str)


def test_examples_inject_keys_from_environment_not_literals():
    """Any example that builds an sdk_key config must read it from the
    environment (or use an obvious placeholder), never embed a real secret."""
    import re

    # Match an sdk_key=<string literal> assignment, e.g. SDKConfig(sdk_key="abc").
    literal_key = re.compile(r"""sdk_key\s*=\s*['"]([^'"]+)['"]""")
    allowed_placeholders = {"your-sdk-key-here", ""}
    for name in EXAMPLE_FILES:
        text = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
        for match in literal_key.finditer(text):
            value = match.group(1)
            assert value in allowed_placeholders, (
                f"examples/{name} embeds a literal sdk_key {value!r}; "
                f"inject it from the environment instead"
            )
        # If an example uses sdk_key at all, it should source it from the env.
        if "SDKConfig(sdk_key=" in text:
            assert "CONVERT_SDK_KEY" in text, (
                f"examples/{name} uses sdk_key without reading CONVERT_SDK_KEY"
            )


# --- README drift protection --------------------------------------------------


def test_readme_is_not_scaffold_form():
    text = README.read_text(encoding="utf-8")
    assert "Foundation scaffold" not in text, "README still in Story 1.1 scaffold form"
    assert "placeholders in this release" not in text


def test_readme_documents_the_implemented_public_api():
    text = README.read_text(encoding="utf-8")
    for token in (
        "convert-python-sdk",  # distribution name
        "convert_sdk",  # import package
        "SDKConfig",
        "create_context",
        "run_experience",
        "run_feature",
        "initialize()",
    ):
        assert token in text, f"README is missing documentation for {token!r}"


def test_readme_does_not_document_unimplemented_apis():
    text = README.read_text(encoding="utf-8")
    # The reconciled-but-deferred factory was never implemented on this branch.
    assert "ConvertSDK.create(" not in text


@pytest.mark.parametrize(
    "symbol",
    ["Core", "Context", "SDKConfig", "ExperienceResult", "FeatureResult", "FeatureStatus"],
)
def test_readme_only_references_real_public_symbols(symbol):
    """Every public symbol the README leans on must be importable."""
    module = importlib.import_module("convert_sdk")
    assert hasattr(module, symbol), f"README references {symbol} but it is not public"
