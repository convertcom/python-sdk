from __future__ import annotations

from collections.abc import Mapping


def object_not_empty(value: object) -> bool:
    return isinstance(value, Mapping) and len(value) > 0


def object_deep_merge(*objects: object) -> dict:
    result: dict = {}
    for obj in objects:
        if not isinstance(obj, Mapping):
            continue
        for key, value in obj.items():
            existing = result.get(key)
            if isinstance(existing, Mapping) and isinstance(value, Mapping):
                result[key] = object_deep_merge(existing, value)
            else:
                result[key] = value
    return result
