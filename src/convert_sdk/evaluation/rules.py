"""Minimal local rule evaluation helpers for FullStack config data.

Match operators mirror the JavaScript SDK's ``Comparisons`` class
(``packages/utils/src/comparisons.ts``). The contract is intentionally
case-insensitive for string-shaped operators (``equals`` / ``matches`` /
``contains`` / ``startsWith`` / ``endsWith`` / ``regexMatches`` / ``isIn``)
and type-tolerant for numeric operators (``less`` / ``lessEqual``) — the
JS implementation returns ``false`` on type mismatch rather than raising,
and any divergence here causes the same input to produce different
audience matches across SDKs.
"""

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
    if match_type in {"equals", "matches", "equalsNumber"}:
        return _equals(actual, expected)
    if match_type in {"less", "lessEqual"}:
        return _less(actual, expected, allow_equal=match_type == "lessEqual")
    if match_type == "contains":
        return _contains(actual, expected)
    if match_type == "startsWith":
        return _starts_with(actual, expected)
    if match_type == "endsWith":
        return _ends_with(actual, expected)
    if match_type == "regexMatches":
        return _regex_matches(actual, expected)
    if match_type == "isIn":
        return _is_in(actual, expected)
    # Unknown match type: parity behaviour with JS would fall back to the
    # comparison processor's default branch. JS returns false for unknown
    # operators after warning; we mirror that by returning false rather
    # than the previous lenient ``actual == expected`` shortcut.
    return False


def _equals(value: Any, test_against: Any) -> bool:
    # JS ``Comparisons.equals``:
    #   - if value is an array, return ``testAgainst in array``
    #   - if value is a non-empty mapping, return ``str(testAgainst) in keys``
    #   - else stringify both, lowercase, compare
    if isinstance(value, (list, tuple)):
        return test_against in value or str(test_against) in (str(item) for item in value)
    if isinstance(value, Mapping) and len(value) > 0:
        return str(test_against) in (str(key) for key in value)
    return _str_lower(value) == _str_lower(test_against)


def _less(value: Any, test_against: Any, *, allow_equal: bool) -> bool:
    # JS coerces numeric-looking strings via ``isNumeric`` and returns
    # false when ``typeof value !== typeof testAgainst`` rather than
    # raising. Mirror that: return false on un-coercible input.
    coerced_value = _coerce_numeric(value)
    coerced_test = _coerce_numeric(test_against)
    if coerced_value is None or coerced_test is None:
        return False
    if allow_equal:
        return coerced_value <= coerced_test
    return coerced_value < coerced_test


def _contains(value: Any, test_against: Any) -> bool:
    # JS ``contains`` lowercases both, returns true when testAgainst is
    # whitespace-only after trimming, and otherwise does a substring
    # check. The legacy Python branch that handled list/tuple values
    # was a non-parity addition (JS handles arrays via ``equals``, not
    # ``contains``) and is removed.
    str_value = _str_lower(value)
    str_test = _str_lower(test_against)
    if str_test.strip() == "":
        return True
    return str_test in str_value


def _starts_with(value: Any, test_against: Any) -> bool:
    return _str_lower(value).startswith(_str_lower(test_against))


def _ends_with(value: Any, test_against: Any) -> bool:
    return _str_lower(value).endswith(_str_lower(test_against))


def _regex_matches(value: Any, test_against: Any) -> bool:
    # JS uses ``new RegExp(testAgainst, 'i')`` which is case-insensitive
    # against the lowercased value. Python ``re.IGNORECASE`` provides
    # the same behaviour without manually lowercasing the input.
    pattern = str(test_against) if test_against is not None else ""
    haystack = str(value) if value is not None else ""
    try:
        return re.search(pattern, haystack, flags=re.IGNORECASE) is not None
    except re.error:
        # Malformed pattern: JS would throw at construction time and the
        # rule manager would catch upstream; mirror the safe-false here.
        return False


def _is_in(value: Any, test_against: Any) -> bool:
    # JS ``isIn`` splits both sides by ``|``, lowercases ``testAgainst``
    # only, and returns true when any segment of value appears in the
    # testAgainst list.
    splitter = "|"
    matched_values = [str(item) for item in str(value if value is not None else "").split(splitter)]
    if isinstance(test_against, (list, tuple)):
        candidates = [str(item).lower() for item in test_against]
    elif isinstance(test_against, str):
        candidates = [item.lower() for item in test_against.split(splitter)]
    else:
        candidates = []
    return any(item in candidates for item in matched_values)


def _str_lower(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower()


def _coerce_numeric(value: Any) -> float | None:
    # JS ``isNumeric`` accepts numeric strings and numbers; rejects
    # anything else. Mirror by trying ``float()`` and returning None on
    # failure rather than raising.
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None
