"""Public import-boundary tests for the Convert Python SDK (Story 1.1).

These tests freeze the canonical public surface: ``Core``, ``Context``, and
``__version__`` are importable from the top-level ``convert_sdk`` package, the
version is single-sourced, and no internal modules leak into the public API.
"""

import convert_sdk


def test_public_symbols_importable():
    """The frozen public boundary must be importable from convert_sdk."""
    from convert_sdk import Core, Context, __version__  # noqa: F401

    assert Core is not None
    assert Context is not None
    assert isinstance(__version__, str)


def test_version_is_frozen_value():
    """Story 1.1 freezes the initial version at 0.1.0."""
    from convert_sdk import __version__

    assert __version__ == "0.1.0"


def test_version_single_sourced():
    """__version__ must be sourced from convert_sdk.version (single source)."""
    from convert_sdk import __version__ as pkg_version
    from convert_sdk.version import __version__ as module_version

    assert pkg_version == module_version


def test_no_internal_modules_reexported():
    """Only the approved surface is public; internal module names must not be
    re-exported at the top level."""
    approved = {"Core", "Context", "__version__"}

    declared = getattr(convert_sdk, "__all__", None)
    assert declared is not None, "convert_sdk must declare __all__"
    assert set(declared) == approved, (
        f"public __all__ drifted: {sorted(declared)} != {sorted(approved)}"
    )

    # Internal module names must not appear as re-exported public attributes.
    for internal in ("core", "context", "version"):
        assert internal not in declared
