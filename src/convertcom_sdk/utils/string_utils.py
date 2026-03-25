from __future__ import annotations

import re

from .hashing import murmurhash3_x86_32


_NUMERIC_RE = re.compile(r"^-?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)$")


def camel_case(value: str) -> str:
    words = re.split(r"\s+", value.strip())
    if not words or words == [""]:
        return ""
    first, *rest = words
    return first[:1].lower() + first[1:] + "".join(
        word[:1].upper() + word[1:] for word in rest
    )


def generate_hash(value: str, seed: int = 9999) -> int:
    return murmurhash3_x86_32(str(value), seed)


def is_numeric(value: str | int | float) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == value and value not in (float("inf"), float("-inf"))
    if not isinstance(value, str) or not _NUMERIC_RE.match(value):
        return False
    try:
        parsed = float(value.replace(",", ""))
    except ValueError:
        return False
    return parsed == parsed and parsed not in (float("inf"), float("-inf"))


def to_number(value: str | int | float) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    parts = str(value).split(",")
    if parts and parts[0] == "0":
        normalized = str(value).replace(",", ".")
    else:
        normalized = str(value).replace(",", "")
    return float(normalized)
