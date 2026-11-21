"""``version_info`` accepts ASCII digits only.

``int()`` converts any Unicode decimal digit, so a pattern built on ``\\d``
would turn an Arabic-Indic stamp into a tuple instead of failing the build.
"""

from __future__ import annotations

import re

import pytest

import convert_sdk.version as version_module


@pytest.mark.parametrize(
    "value",
    [
        "\u0661.\u0662.\u0663",  # Arabic-Indic 1.2.3
        "\u06f1.\u06f2.\u06f3",  # Extended Arabic-Indic 1.2.3
        "\uff11.\uff12.\uff13",  # Fullwidth 1.2.3
        "1.\u0662.3",  # one non-ASCII component among ASCII ones
        "1.2.\u0663",
    ],
)
def test_parse_rejects_non_ascii_digits_naming_the_value(value):
    with pytest.raises(ValueError, match=re.escape(repr(value))):
        version_module._parse_version_info(value)
