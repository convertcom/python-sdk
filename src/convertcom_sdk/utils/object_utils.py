from __future__ import annotations

from collections.abc import Mapping


def object_not_empty(value: object) -> bool:
    return isinstance(value, Mapping) and len(value) > 0
