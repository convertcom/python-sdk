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

import re
from typing import Any, Callable, Mapping, Optional, Sequence

from convert_sdk.logging import log_mutual_exclusion_target_not_found

#: qs-04 mutual-exclusion audience rule type (`bucketed_into_experience_key`).
#: Public (not underscore-prefixed) because it is a cross-module contract
#: value: this module (``rules.py``) owns the constant, and (as of PY-3) also
#: owns the dispatch on it — see :func:`_resolve_bucketed_into_experience_key`
#: and :func:`_resolve_audience` below — the same public-constant convention
#: used by ``evaluation/bucketing.py``'s ``DEFAULT_HASH_SEED`` /
#: ``DEFAULT_MAX_TRAFFIC`` for values shared across module boundaries.
RULE_TYPE_BUCKETED_INTO_EXPERIENCE_KEY = "bucketed_into_experience_key"

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
        return str(test_against) in {str(k) for k in value}
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


def _is_in(values: Any, test_against: Any, splitter: str = "|") -> bool:
    """Check whether any element of ``values`` appears in ``test_against``.

    Mirrors ``Comparisons.isIn`` in the JS SDK
    (``packages/utils/src/comparisons.ts``):

    * ``values`` is coerced to a string and split by ``splitter`` (default
      ``"|"``).  Each resulting element is kept as-is (NOT lowercased) for
      membership lookup.
    * ``test_against`` is either a string split by ``splitter``, already a
      list/tuple, or a scalar value wrapped in a one-element list.  Each
      element is lowercased before the lookup.
    * The membership test therefore is: any visitor-value token (verbatim)
      appears in the lowercased test-against list.  Because the visitor token
      is also compared verbatim the match is case-sensitive from the visitor's
      side — mirroring the JS source of truth exactly.

    The ``splitter`` parameter is exposed for comma-delimited configs
    (``splitter=","``); callers may pass it via extra rule-level metadata.
    The default ``"|"`` matches both the JS and PHP SDKs.
    """
    matched_values = [str(item) for item in str(values).split(splitter)]

    test_against_list: list[str]
    if isinstance(test_against, str):
        test_against_list = test_against.split(splitter)
    elif isinstance(test_against, (list, tuple)):
        test_against_list = [str(item) for item in test_against]
    else:
        # Scalar: wrap in a single-item list (mirrors JS ``testAgainst = []``
        # fallback path; a non-string, non-array testAgainst becomes an empty
        # array in JS.  PHP wraps scalars in a list.  We follow PHP here for
        # practical parity: a plain number testAgainst is supported.)
        test_against_list = [str(test_against)]

    # Lowercase only the test-against side (mirrors JS exactly).
    lowered = [item.lower() for item in test_against_list]

    return any(item in lowered for item in matched_values)


def _regex_matches(value: Any, test_against: Any) -> bool:
    """Test ``value`` against a regex pattern ``test_against``.

    Mirrors ``Comparisons.regexMatches`` in the JS SDK
    (``packages/utils/src/comparisons.ts``):

    * ``value`` is coerced to a lower-cased string.
    * ``test_against`` is coerced to a string (pattern) — the case flag is
      applied by the regex engine itself (``re.IGNORECASE``), so the pattern
      is NOT lowercased.
    * An invalid (unparseable) pattern returns ``False`` — never raises, to
      match PHP's ``preg_match`` error suppression.
    """
    str_value = str(value).lower()
    pattern = str(test_against)
    try:
        return bool(re.search(pattern, str_value, re.IGNORECASE))
    except re.error:
        return False


# match_type -> comparison callable. Aliases mirror the JS Comparisons class.
# Typed as Callable[..., bool] to accommodate operators with different arities
# (e.g. _is_in has an optional splitter parameter).
_COMPARATORS: dict[str, Callable[..., bool]] = {
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
    "isIn": _is_in,
    "regexMatches": _regex_matches,
}

# Operators that are meaningful even when the key is absent from the data.
_EXISTENCE_OPERATORS = {"exists", "not_exists", "doesNotExist"}


def _process_rule_item(data: Optional[Mapping[str, Any]], rule: Mapping[str, Any]) -> bool:
    """Evaluate a single rule item against a key-value ``data`` mapping."""
    matching = rule.get("matching") or {}
    match_type = matching.get("match_type")
    negated = bool(matching.get("negated", False))
    comparator = _COMPARATORS.get(match_type) if match_type is not None else None
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
    return any(_process_rule_item(data, item) is True for item in items)


def _process_and(data: Optional[Mapping[str, Any]], rules_subset: Mapping[str, Any]) -> bool:
    """AND: every OR_WHEN block must be true."""
    blocks: Sequence[Mapping[str, Any]] = rules_subset.get("AND") or []
    if not blocks:
        return False
    return all(_process_or_when(data, block) is True for block in blocks)


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
    return any(_process_and(data, branch) is True for branch in or_branches)


# ---------------------------------------------------------------------------
# Experience-level qualification (matchRulesByField parity, MVP subset).
# ---------------------------------------------------------------------------


def _sole_rule_item(rules: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """Return the single rule item at the bottom of ``rules``'s
    ``OR[AND[OR_WHEN[...]]]`` tree when it is the SOLE item in that tree
    (exactly one ``OR`` branch, one ``AND`` block, one ``OR_WHEN`` item) — else
    ``None`` for any other (empty, malformed, or mixed multi-item) tree.

    Used to detect a "sole-exclusion-rule-per-audience-tree" audience (qs-04):
    an audience whose entire rule tree is exactly one rule element (in
    practice, a ``bucketed_into_experience_key`` exclusion). A mixed tree
    (more than one ``OR``/``AND``/``OR_WHEN`` entry) is NOT sole and falls
    through to the generic :func:`is_rule_matched` walk unchanged — no served
    config mixes the exclusion rule into a generic audience's tree (backend
    registration is a separate spec), so this is a conservative fail-closed
    detection, never a guess.
    """
    if not isinstance(rules, Mapping):
        return None
    or_branches: Sequence[Mapping[str, Any]] = rules.get("OR") or []
    if len(or_branches) != 1:
        return None
    and_blocks: Sequence[Mapping[str, Any]] = or_branches[0].get("AND") or []
    if len(and_blocks) != 1:
        return None
    or_when_items: Sequence[Mapping[str, Any]] = and_blocks[0].get("OR_WHEN") or []
    if len(or_when_items) != 1:
        return None
    return or_when_items[0]


def _resolve_bucketed_into_experience_key(
    rule: Mapping[str, Any],
    snapshot: Any,
    sticky_bucketing: Optional[Mapping[str, str]],
) -> bool:
    """Resolve a SOLE ``bucketed_into_experience_key`` audience rule (qs-04),
    read-only, against the visitor's stored bucketing decisions.

    Mirrors the spec's resolution algorithm
    (``qs-04-mutual-exclusion-rule.md``):

    * ``target = snapshot.get_experience_by_key(rule["value"])``
    * ``bucketed_raw = target is not None AND str(target["id"]) in
      sticky_bucketing`` — never the bucketing hash, never a write.
    * ``matched = (not bucketed_raw) if negated else bucketed_raw``
      (negation applied LAST, after ``bucketed_raw`` is resolved).

    An unresolvable target key logs a WARNING naming it
    (:func:`~convert_sdk.logging.log_mutual_exclusion_target_not_found`,
    AC8) and ``bucketed_raw`` stays ``False`` — with ``negated: true`` the
    exclusion dissolves (mirrors web semantics for an archived/unknown
    target).
    """
    matching = rule.get("matching") or {}
    negated = bool(matching.get("negated", False))
    target_key = rule.get("value")
    target = snapshot.get_experience_by_key(target_key)

    bucketed_raw = False
    if target is None:
        log_mutual_exclusion_target_not_found(target_key=str(target_key))
    else:
        target_id = target.get("id")
        bucketed_raw = bool(
            target_id is not None
            and sticky_bucketing is not None
            and str(target_id) in sticky_bucketing
        )

    return (not bucketed_raw) if negated else bucketed_raw


def _resolve_audience(
    audience: Mapping[str, Any],
    snapshot: Any,
    visitor_attributes: Mapping[str, Any],
    sticky_bucketing: Optional[Mapping[str, str]],
) -> bool:
    """Resolve a single referenced audience.

    A generic audience is matched against ``visitor_attributes`` via the
    unchanged :func:`is_rule_matched` walk. A *sole-exclusion* audience (its
    entire rule tree is one ``bucketed_into_experience_key`` item, per
    :func:`_sole_rule_item`) is instead resolved read-only against
    ``sticky_bucketing`` via :func:`_resolve_bucketed_into_experience_key` —
    ``visitor_attributes`` is never consulted for that audience (AC7
    structural data-isolation guard).
    """
    rules = audience.get("rules")
    if not rules:
        return False
    sole_item = _sole_rule_item(rules)
    if (
        sole_item is not None
        and sole_item.get("rule_type") == RULE_TYPE_BUCKETED_INTO_EXPERIENCE_KEY
    ):
        return _resolve_bucketed_into_experience_key(sole_item, snapshot, sticky_bucketing)
    return is_rule_matched(visitor_attributes, rules)


def _matches_any_audience(
    audience_ids: Sequence[str],
    snapshot: Any,
    visitor_attributes: Mapping[str, Any],
    sticky_bucketing: Optional[Mapping[str, str]] = None,
) -> bool:
    """At least one referenced audience must match (``matching_options.audiences
    != "all"`` — today's sole policy, and the default when absent/unset,
    AC7)."""
    for audience_id in audience_ids:
        audience = snapshot.get_audience_by_id(str(audience_id))
        if audience is None:
            continue
        if _resolve_audience(audience, snapshot, visitor_attributes, sticky_bucketing):
            return True
    return False


def _matches_all_audiences(
    audience_ids: Sequence[str],
    snapshot: Any,
    visitor_attributes: Mapping[str, Any],
    sticky_bucketing: Optional[Mapping[str, str]] = None,
) -> bool:
    """Every referenced (resolvable) audience must match
    (``matching_options.audiences == "all"``, qs-04 AC6).

    Mirrors ``php-sdk/packages/Data/src/DataManager.php:456``:
    ``count(matched) === count(toCheck)``, where ``toCheck`` is the subset of
    ``audience_ids`` that resolve to a real audience in ``snapshot`` — an
    audience id with no matching audience is skipped from both counts (as
    :func:`_matches_any_audience` already does), so referencing zero
    resolvable audiences is vacuously "all matched" (``0 == 0``), mirroring
    the PHP oracle's "not restricted" fallback for that edge.
    """
    to_check = 0
    matched = 0
    for audience_id in audience_ids:
        audience = snapshot.get_audience_by_id(str(audience_id))
        if audience is None:
            continue
        to_check += 1
        if _resolve_audience(audience, snapshot, visitor_attributes, sticky_bucketing):
            matched += 1
    return matched == to_check


def qualifies(
    experience: Mapping[str, Any],
    snapshot: Any,
    *,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
    sticky_bucketing: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether a visitor qualifies for ``experience`` against ``snapshot``.

    Mirrors the JS ``matchRulesByField`` MVP policy:

    * Location: if the experience has a ``site_area`` rule set, it must match the
      ``location_attributes``; an absent/empty ``site_area`` is unrestricted.
    * Audience: if the experience references audiences, ``experience.settings.
      matching_options.audiences`` picks the combination policy — ``"all"``
      requires every referenced (resolvable) audience to match; anything else
      (``"any"``, absent, or no ``settings`` at all) requires at least one
      referenced audience to match (today's exact, pre-qs-04 policy — the
      mandatory zero-regression default, AC7). An absent/empty audiences list
      is unrestricted.

    ``sticky_bucketing`` is the optional visitor bucketing-decision map (qs-03)
    threaded through ONLY to the audience-level resolution helpers above —
    never merged into ``visitor_attributes`` — so a ``bucketed_into_
    experience_key`` sole-exclusion audience (qs-04) can resolve against
    stored bucketing state while every generic audience/location rule keeps
    reading exclusively from the caller-scoped attribute dicts (AC7
    structural guard).

    Missing attribute dicts are treated as empty (no restriction can be
    satisfied for a restricted experience, so a restricted experience without
    the corresponding attributes does not qualify). Never raises for misses.
    """
    visitor_attributes = visitor_attributes or {}
    location_attributes = location_attributes or {}

    # Location qualification (site_area rule set).
    site_area = experience.get("site_area")
    if site_area and not is_rule_matched(location_attributes, site_area):
        return False

    # Audience qualification. Kept as an explicit guard clause (parallel to the
    # site_area guard above) rather than a compound negated return for clarity.
    audience_ids = experience.get("audiences") or []
    if audience_ids:
        settings = experience.get("settings") or {}
        matching_options = settings.get("matching_options") or {}
        combination = matching_options.get("audiences")
        if combination == "all":
            audiences_matched = _matches_all_audiences(
                audience_ids, snapshot, visitor_attributes, sticky_bucketing
            )
        else:
            audiences_matched = _matches_any_audience(
                audience_ids, snapshot, visitor_attributes, sticky_bucketing
            )
        if not audiences_matched:
            return False

    return True
