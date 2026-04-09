"""Minimal local rule evaluation helpers for FullStack config data."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence


def evaluate_rules(
    rules: Mapping[str, Any] | None,
    attributes: Mapping[str, Any],
) -> bool:
    """Evaluate nested audience/location rules against request attributes."""

    if not rules:
        return True

    if "OR" in rules:
        return any(
            _evaluate_and_group(group, attributes)
            for group in _iter_rule_mappings(rules.get("OR"))
        )
    if "AND" in rules:
        return _evaluate_and_group(rules, attributes)
    if "OR_WHEN" in rules:
        return _evaluate_or_when_group(rules, attributes)
    return _evaluate_rule(rules, attributes)


def _iter_rule_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _evaluate_and_group(
    group: Mapping[str, Any],
    attributes: Mapping[str, Any],
) -> bool:
    and_conditions = group.get("AND")
    if and_conditions is None:
        return _evaluate_or_when_group(group, attributes)

    return all(
        _evaluate_or_when_group(condition, attributes)
        for condition in _iter_rule_mappings(and_conditions)
    )


def _evaluate_or_when_group(
    condition: Mapping[str, Any],
    attributes: Mapping[str, Any],
) -> bool:
    rules = condition.get("OR_WHEN")
    if rules is None:
        return _evaluate_rule(condition, attributes)

    return any(_evaluate_rule(rule, attributes) for rule in _iter_rule_mappings(rules))


def _evaluate_rule(
    rule: Mapping[str, Any],
    attributes: Mapping[str, Any],
) -> bool:
    key = rule.get("key")
    if key in (None, ""):
        return False

    actual = attributes.get(str(key))
    if actual is None:
        return False

    matching = rule.get("matching")
    match_type = "equals"
    negated = False
    if isinstance(matching, Mapping):
        match_type = str(matching.get("match_type", match_type))
        negated = bool(matching.get("negated", False))

    expected = rule.get("value")
    result = _match_value(actual, expected, match_type)
    return not result if negated else result


def _match_value(actual: Any, expected: Any, match_type: str) -> bool:
    if match_type in {"equals", "matches"}:
        return actual == expected or str(actual) == str(expected)
    if match_type == "equalsNumber":
        return _to_number(actual) == _to_number(expected)
    if match_type == "less":
        return _to_number(actual) < _to_number(expected)
    if match_type == "lessEqual":
        return _to_number(actual) <= _to_number(expected)
    if match_type == "contains":
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
            return expected in actual
        return False
    if match_type == "startsWith":
        return str(actual).startswith(str(expected))
    if match_type == "endsWith":
        return str(actual).endswith(str(expected))
    if match_type == "regexMatches":
        return re.search(str(expected), str(actual)) is not None
    return actual == expected


def _to_number(value: Any) -> float:
    if isinstance(value, bool):
        return float(int(value))
    return float(value)
