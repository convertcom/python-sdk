"""Public import-boundary tests for the Convert Python SDK (Story 1.1).

These tests freeze the canonical public surface: ``Core``, ``Context``, and
``__version__`` are importable from the top-level ``convert_sdk`` package, the
version is single-sourced, and no internal modules leak into the public API.
"""

import convert_sdk


def test_public_symbols_importable():
    """The frozen public boundary must be importable from convert_sdk."""
    from convert_sdk import Core, Context, __version__

    assert Core is not None
    assert Context is not None
    assert isinstance(__version__, str)


def test_version_is_dev_placeholder():
    """The dev placeholder in version.py is '0.0.0'; the real version is
    stamped by the release pipeline at build time (semantic-release prepareCmd)
    and is never committed. This test confirms the placeholder is consistent."""
    from convert_sdk import __version__

    assert __version__ == "0.0.0"


def test_version_single_sourced():
    """__version__ must be sourced from convert_sdk.version (single source)."""
    from convert_sdk import __version__ as pkg_version
    from convert_sdk.version import __version__ as module_version

    assert pkg_version == module_version


def test_frozen_story_1_1_boundary_still_public():
    """The Story 1.1 frozen trio must remain in the public surface unchanged.

    Story 1.2 *extends* the public surface (config + error types) but must not
    remove or rename the frozen Story 1.1 boundary.
    """
    frozen = {"Core", "Context", "__version__"}

    declared = getattr(convert_sdk, "__all__", None)
    assert declared is not None, "convert_sdk must declare __all__"
    assert frozen.issubset(set(declared)), (
        f"frozen Story 1.1 boundary dropped from public __all__: "
        f"missing {sorted(frozen - set(declared))}"
    )

    # Internal module names must not appear as re-exported public attributes.
    for internal in ("core", "context", "version", "config", "errors"):
        assert internal not in declared


def test_story_1_4_exposes_experience_result_additively():
    """Story 1.4 adds ExperienceResult to the public surface without dropping
    the frozen Story 1.1 trio."""
    from convert_sdk import ExperienceResult  # noqa: F401

    declared = set(convert_sdk.__all__)
    assert "ExperienceResult" in declared
    # Frozen trio still present.
    assert {"Core", "Context", "__version__"}.issubset(declared)
    # Internal evaluation modules must not leak into the public surface.
    for internal in ("evaluation", "results", "bucketing", "rules", "experiences"):
        assert internal not in declared


def test_feature_result_and_status_exposed_additively():
    """The minimal feature-resolution foundation adds FeatureResult and
    FeatureStatus to the public surface without dropping the frozen trio."""
    from convert_sdk import FeatureResult, FeatureStatus  # noqa: F401

    declared = set(convert_sdk.__all__)
    assert "FeatureResult" in declared
    assert "FeatureStatus" in declared
    assert {"Core", "Context", "__version__"}.issubset(declared)
    for internal in ("features",):
        assert internal not in declared
