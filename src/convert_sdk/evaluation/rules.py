"""Audience and location rule qualification for local evaluation (Story 1.4).

This module implements the MVP subset of the JavaScript SDK's rule engine
needed to qualify a visitor for an experience against the current FullStack
config shapes — audience rules (matched against request-time *visitor*
attributes) and ``site_area`` location rules (matched against request-time
*location* attributes).

Parity references:
- ``../javascript-sdk/packages/rules/src/rule-manager.ts`` — the nested
  ``OR / AND / OR_WHEN`` boolean tree and ``matching.match_type`` dispatch.
- ``../javascript-sdk/packages/utils/src/comparisons.ts`` — the comparison
  operator semantics (case-insensitive string compares, negation handling).
- ``../javascript-sdk/packages/data/src/data-manager.ts`` ``matchRulesByField``
  — the experience-level qualification policy: an empty or absent audiences /
  locations list means *unrestricted* (qualifies); a non-empty list must match.

All normal misses return ``False`` / non-qualification — never an exception.
Evaluation reads only the immutable snapshot and the caller-scoped attribute
dicts; it never mutates either.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Comparison operators (mirror packages/utils/src/comparisons.ts).
# Each operator takes (data_value, test_against) and returns a bool BEFORE
# negation is applied by the caller.
# ---------------------------------------------------------------------------


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    try:
        float(value.replace(",", ""))
        return True
    except (ValueError, AttributeError):
        return False


def _to_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", ""))


def _equals(value: Any, test_against: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return test_against in value
    if isinstance(value, Mapping):
        return str(test_against) in {str(k) for k in value.keys()}
    return str(value).lower() == str(test_against).lower()


def _contains(value: Any, test_against: Any) -> bool:
    haystack = str(value).lower()
    needle = str(test_against).lower()
    if needle.strip() == "":
        return True
    return needle in haystack


def _starts_with(value: Any, test_against: Any) -> bool:
    return str(value).lower().startswith(str(test_against).lower())


def _ends_with(value: Any, test_against: Any) -> bool:
    return str(value).lower().endswith(str(test_against).lower())


def _less(value: Any, test_against: Any) -> bool:
    v = _to_number(value) if _is_numeric(value) else value
    t = _to_number(test_against) if _is_numeric(test_against) else test_against
    if type(v) is not type(t):
        return False
    return v < t


def _less_equal(value: Any, test_against: Any) -> bool:
    v = _to_number(value) if _is_numeric(value) else value
    t = _to_number(test_against) if _is_numeric(test_against) else test_against
    if type(v) is not type(t):
        return False
    return v <= t


def _exists(value: Any, _test_against: Any) -> bool:
    return value is not None and value != ""


def _not_exists(value: Any, _test_against: Any) -> bool:
    return value is None or value == ""


# match_type -> comparison callable. Aliases mirror the JS Comparisons class.
_COMPARATORS = {
    "equals": _equals,
    "equalsNumber": _equals,
    "matches": _equals,
    "contains": _contains,
    "startsWith": _starts_with,
    "endsWith": _ends_with,
    "less": _less,
    "lessEqual": _less_equal,
    "exists": _exists,
    "not_exists": _not_exists,
    "doesNotExist": _not_exists,
}

# Operators that are meaningful even when the key is absent from the data.
_EXISTENCE_OPERATORS = {"exists", "not_exists", "doesNotExist"}


def _process_rule_item(data: Optional[Mapping[str, Any]], rule: Mapping[str, Any]) -> bool:
    """Evaluate a single rule item against a key-value ``data`` mapping."""
    matching = rule.get("matching") or {}
    match_type = matching.get("match_type")
    negated = bool(matching.get("negated", False))
    comparator = _COMPARATORS.get(match_type)
    if comparator is None:
        return False

    key = rule.get("key")
    test_against = rule.get("value", "")

    data_value: Any = None
    found = False
    if isinstance(data, Mapping):
        for data_key, value in data.items():
            if str(data_key) == str(key):
                data_value = value
                found = True
                break

    if not found and match_type not in _EXISTENCE_OPERATORS:
        # Key absent and operator needs a value -> no match (JS returns false).
        return False

    result = comparator(data_value, test_against)
    return (not result) if negated else bool(result)


def _process_or_when(data: Optional[Mapping[str, Any]], rules_subset: Mapping[str, Any]) -> bool:
    """OR_WHEN: any rule item true -> true."""
    items: Sequence[Mapping[str, Any]] = rules_subset.get("OR_WHEN") or []
    if not items:
        return False
    for item in items:
        if _process_rule_item(data, item) is True:
            return True
    return False


def _process_and(data: Optional[Mapping[str, Any]], rules_subset: Mapping[str, Any]) -> bool:
    """AND: every OR_WHEN block must be true."""
    blocks: Sequence[Mapping[str, Any]] = rules_subset.get("AND") or []
    if not blocks:
        return False
    for block in blocks:
        if _process_or_when(data, block) is not True:
            return False
    return True


def is_rule_matched(
    data: Optional[Mapping[str, Any]],
    rule: Optional[Mapping[str, Any]],
) -> bool:
    """Evaluate a nested ``OR / AND / OR_WHEN`` rule set against ``data``.

    Returns ``True`` only if at least one top-level ``OR`` branch (an ``AND``
    block) fully matches. Returns ``False`` for any miss, malformed rule, or
    missing data — never raises for normal evaluation outcomes.
    """
    if not rule or not isinstance(rule, Mapping):
        return False
    or_branches: Sequence[Mapping[str, Any]] = rule.get("OR") or []
    if not or_branches:
        return False
    for branch in or_branches:
        if _process_and(data, branch) is True:
            return True
    return False


# ---------------------------------------------------------------------------
# Experience-level qualification (matchRulesByField parity, MVP subset).
# ---------------------------------------------------------------------------


def _matches_any_audience(
    audience_ids: Sequence[str],
    snapshot: Any,
    visitor_attributes: Mapping[str, Any],
) -> bool:
    """At least one referenced audience must match the visitor attributes."""
    for audience_id in audience_ids:
        audience = snapshot.get_audience_by_id(str(audience_id))
        if audience is None:
            continue
        rules = audience.get("rules")
        if rules and is_rule_matched(visitor_attributes, rules):
            return True
    return False


def qualifies(
    experience: Mapping[str, Any],
    snapshot: Any,
    *,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return whether a visitor qualifies for ``experience`` against ``snapshot``.

    Mirrors the JS ``matchRulesByField`` MVP policy:

    * Location: if the experience has a ``site_area`` rule set, it must match the
      ``location_attributes``; an absent/empty ``site_area`` is unrestricted.
    * Audience: if the experience references audiences, at least one referenced
      audience's rules must match the ``visitor_attributes``; an absent/empty
      audiences list is unrestricted.

    Missing attribute dicts are treated as empty (no restriction can be
    satisfied for a restricted experience, so a restricted experience without
    the corresponding attributes does not qualify). Never raises for misses.
    """
    visitor_attributes = visitor_attributes or {}
    location_attributes = location_attributes or {}

    # Location qualification (site_area rule set).
    site_area = experience.get("site_area")
    if site_area:
        if not is_rule_matched(location_attributes, site_area):
            return False

    # Audience qualification.
    audience_ids = experience.get("audiences") or []
    if audience_ids:
        if not _matches_any_audience(audience_ids, snapshot, visitor_attributes):
            return False

    return True
