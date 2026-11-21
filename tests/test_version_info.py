"""Tests for ``convert_sdk.version.version_info``.

``version_info`` is the (major, minor, patch) tuple of ints parsed from
``__version__``. The module is read as an attribute namespace so a missing
name fails as an ``AttributeError``, not as an import error.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

import convert_sdk.version as version_module

VERSION_SOURCE = Path(version_module.__file__)
STAMP_PATTERN = re.compile(r'__version__ = "[^"]*"')


def _exec_with_version(value: str) -> types.ModuleType:
    """Run a copy of version.py with ``__version__`` replaced, in a fresh namespace."""
    source = STAMP_PATTERN.sub(lambda _m: f'__version__ = "{value}"', VERSION_SOURCE.read_text())
    namespace = types.ModuleType("version_copy")
    exec(compile(source, str(VERSION_SOURCE), "exec"), namespace.__dict__)
    return namespace


def test_version_info_is_zero_triple_for_placeholder():
    version_info = version_module.version_info

    assert version_info == (0, 0, 0)
    assert isinstance(version_info, tuple)
    assert len(version_info) == 3
    assert all(isinstance(part, int) for part in version_info)


def test_dunder_version_stays_the_placeholder():
    assert version_module.__version__ == "0.0.0"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.4.2", (1, 4, 2)), ("2.0.11", (2, 0, 11)), ("0.0.0", (0, 0, 0))],
)
def test_parse_returns_integer_triple(value, expected):
    assert version_module._parse_version_info(value) == expected


@pytest.mark.parametrize(
    "value",
    ["1.2", "1.2.3.4", "1.2.3-beta.1", "1.2.x", "", "+1.2.3", "1_0.2.3", " 1.2.3", "1..3"],
)
def test_parse_rejects_malformed_value_naming_it(value):
    with pytest.raises(ValueError, match=re.escape(repr(value))):
        version_module._parse_version_info(value)


def test_malformed_dunder_version_raises_at_import():
    with pytest.raises(ValueError, match=re.escape(repr("1.2"))):
        _exec_with_version("1.2")


def test_valid_dunder_version_sets_version_info_at_import():
    namespace = _exec_with_version("9.8.7")

    assert namespace.__version__ == "9.8.7"
    assert namespace.version_info == (9, 8, 7)


def test_version_source_holds_exactly_one_release_stamp_target():
    # release.yml rewrites every match and semantic-release only the first.
    assert len(STAMP_PATTERN.findall(VERSION_SOURCE.read_text())) == 1
