from __future__ import annotations

import json


def cast_type(value: object, kind: str) -> object:
    if kind == "boolean":
        if value == "true":
            return True
        if value == "false":
            return False
        return bool(value)
    if kind == "float":
        if value is True:
            return 1
        if value is False:
            return 0
        return float(value)
    if kind == "json":
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except Exception:
            return str(value)
    if kind == "string":
        return str(value)
    if kind == "integer":
        if value is True:
            return 1
        if value is False:
            return 0
        return int(float(str(value)))
    return value
