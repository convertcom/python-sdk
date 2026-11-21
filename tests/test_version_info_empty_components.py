"""``version_info`` rejects a stamp whose major, minor or patch is empty.

An empty component must fail the pattern with the value's repr, not reach
``int()`` and fail there with a message that names no value.
"""

from __future__ import annotations

import re

import pytest

import convert_sdk.version as version_module


@pytest.mark.parametrize("value", [".2.3", ".0.0", "1..3", "1.2.", "..", "..3"])
def test_parse_rejects_empty_component_naming_the_value(value):
    with pytest.raises(ValueError, match=re.escape(repr(value))):
        version_module._parse_version_info(value)
