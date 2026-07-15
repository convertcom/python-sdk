"""qs-04 PY-4 -- AC7 generic-rule regression lock (mutual-exclusion rule seam).

Spec of record: ``_bmad-output/planning-artifacts/2026-04-06-convert-python-sdk/
qs-04-mutual-exclusion-rule.md`` (AC7: "The 3 generic key/value rule types
behave bit-identically to today... This now also covers the ``matching_options``
default path").

This file is a TEST-ONLY regression LOCK, not TDD -- every test here passes
GREEN immediately against the PY-3 seam already landed in
``src/convert_sdk/evaluation/rules.py``. It proves the seam (the ``sole-exclusion
-audience`` detector + the ``matching_options`` ALL/ANY combinator) did not
change pre-existing generic rule-matching behavior:

* Group 1 -- the 3 generic key/value ``match_type`` operators actually
  exercised across this repo's rule engine (``equals``, ``contains``, ``less``
  -- see the citations on each parametrize row) still match/non-match/negate
  identically through :func:`~convert_sdk.evaluation.rules.is_rule_matched`.
  Concise/parametrized -- NOT a duplicate of ``tests/test_rules.py``'s
  per-operator test functions (those pin the FULL per-operator surface;
  this pins ONLY the 3-representative-operator, match+non-match+negation
  cross-section relevant to the qs-04 seam).
* Group 2 -- ``matching_options`` default-ANY path with PURELY GENERIC
  audiences (no ``bucketed_into_experience_key`` involved at all), plus the
  explicit ALL/ANY boundary contrast. ``tests/test_mutual_exclusion.py``'s
  AC6/AC7 tests already cover a sole-exclusion-audience + generic-audience
  combination; this group is the complementary "zero exclusion rule anywhere"
  case -- multiple purely generic audiences combined via
  ``matching_options.audiences``, proving the ALL/ANY control is
  seam-independent of the new rule type.
* Group 3 -- the "sole-exclusion-rule-per-audience-tree" carry-forward: an
  audience whose rule tree has MORE THAN ONE rule element must never be
  mistaken for a sole-exclusion tree and must fall through, unchanged, to the
  pre-existing :func:`is_rule_matched` walk. Per the spec (AC6 note, qs-04
  line 59) "no served config produces" a genuinely mixed generic+exclusion
  tree, so -- per the sanctioned JS/PHP qs-03 PY-4/SDK-4 precedent
  (``php-sdk/packages/Data/tests/MutualExclusionGenericRegressionTest.php``,
  "Item 3": two generic rules ANDed together) -- two generic rules under AND
  is used as the representative substitute shape.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

import pytest

from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.evaluation import rules
from convert_sdk.evaluation.rules import is_rule_matched, qualifies


def _rule(match_type: str, key: str, value: Any, negated: bool = False) -> Dict[str, Any]:
    """A single-rule-element ``OR[AND[OR_WHEN[...]]]`` tree. Mirrors the
    repo-wide test convention (``tests/test_rules.py:20``,
    ``tests/test_experience_selection.py`` and others each define this exact
    tiny helper locally rather than importing a private helper cross-module --
    see this task's decision-log entry for why re-defining a ~6-line, already
    repo-wide-duplicated helper is the established pattern here, not a
    SonarQube-relevant near-duplicate).
    """
    return {
        "OR": [
            {
                "AND": [
                    {
                        "OR_WHEN": [
                            {"matching": {"match_type": match_type, "negated": negated}, "key": key, "value": value}
                        ]
                    }
                ]
            }
        ]
    }


def _snapshot(experiences: Any, audiences: Any = ()) -> ConfigSnapshot:
    from convert_sdk.config_loader import load_snapshot

    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": list(experiences),
            "audiences": list(audiences),
        }
    )


# ---------------------------------------------------------------------------
# Group 1 -- 3 generic rule types bit-identical (match / non-match / negation)
# ---------------------------------------------------------------------------

# Disk citations proving these 3 match_types are the ones actually exercised
# by this repo's rule engine (not invented ad hoc):
#   equals   -- tests/test_rules.py:29 (match), :31 (non-match), :41-43 (negation)
#   contains -- tests/test_rules.py:35 (match), :37 (non-match)
#   less     -- tests/parity/fixtures/rule_vectors.json:374 (release-blocking
#               JS-parity golden suite's numeric comparator vector)
_GENERIC_VECTORS: Tuple[Tuple[str, str, Any, Mapping[str, Any], bool, bool], ...] = (
    ("equals", "country", "US", {"country": "us"}, False, True),
    ("equals", "country", "US", {"country": "CA"}, False, False),
    ("equals", "country", "US", {"country": "us"}, True, False),
    ("contains", "url", "checkout", {"url": "https://shop/CHECKOUT/cart"}, False, True),
    ("contains", "url", "checkout", {"url": "https://shop/home"}, False, False),
    ("contains", "url", "checkout", {"url": "https://shop/CHECKOUT/cart"}, True, False),
    ("less", "score", 10, {"score": 5}, False, True),
    ("less", "score", 10, {"score": 20}, False, False),
    ("less", "score", 10, {"score": 5}, True, False),
)


@pytest.mark.parametrize(
    "match_type, key, value, data, negated, expected",
    _GENERIC_VECTORS,
    ids=[
        f"{row[0]}_{'match' if row[5] and not row[4] else 'nonmatch' if not row[5] and not row[4] else 'negated'}"
        for row in _GENERIC_VECTORS
    ],
)
def test_generic_rule_types_bit_identical_match_nonmatch_negation(
    match_type: str, key: str, value: Any, data: Mapping[str, Any], negated: bool, expected: bool
) -> None:
    rule = _rule(match_type, key, value, negated=negated)
    assert is_rule_matched(data, rule) is expected


# ---------------------------------------------------------------------------
# Group 2 -- matching_options default-ANY path (purely generic audiences)
# ---------------------------------------------------------------------------

_AUD_1_KEY, _AUD_1_VALUE = "country", "US"
_AUD_2_KEY, _AUD_2_VALUE = "plan", "pro"


def _generic_audience(audience_id: str, key: str, value: str) -> Dict[str, Any]:
    return {"id": audience_id, "key": audience_id, "rules": _rule("equals", key, value)}


def _two_generic_audience_experience(
    matching_options: "str | None",
) -> Tuple[ConfigSnapshot, Dict[str, Any]]:
    """A config with TWO purely-generic audiences (zero
    ``bucketed_into_experience_key`` anywhere) referenced by one experience,
    optionally carrying ``settings.matching_options.audiences``.
    """
    audiences = [
        _generic_audience("aud-1", _AUD_1_KEY, _AUD_1_VALUE),
        _generic_audience("aud-2", _AUD_2_KEY, _AUD_2_VALUE),
    ]
    exp: Dict[str, Any] = {"id": "e1", "key": "exp", "audiences": ["aud-1", "aud-2"], "variations": []}
    if matching_options is not None:
        exp["settings"] = {"matching_options": {"audiences": matching_options}}
    return _snapshot([exp], audiences), exp


def test_default_any_qualifies_when_one_of_several_referenced_audiences_matches() -> None:
    snap, exp = _two_generic_audience_experience(matching_options=None)
    assert qualifies(exp, snap, visitor_attributes={_AUD_1_KEY: _AUD_1_VALUE}) is True


def test_default_any_does_not_qualify_when_no_referenced_audience_matches() -> None:
    snap, exp = _two_generic_audience_experience(matching_options=None)
    assert qualifies(exp, snap, visitor_attributes={}) is False


def test_matching_options_absent_behaves_identically_to_explicit_any() -> None:
    """``matching_options`` ABSENT must resolve bit-identically to the explicit
    ``"any"`` value -- pinning the equivalence the spec's zero-regression
    default policy relies on (AC7)."""
    attrs = {_AUD_1_KEY: _AUD_1_VALUE}
    snap_absent, exp_absent = _two_generic_audience_experience(matching_options=None)
    snap_any, exp_any = _two_generic_audience_experience(matching_options="any")

    assert qualifies(exp_absent, snap_absent, visitor_attributes=attrs) is True
    assert qualifies(exp_any, snap_any, visitor_attributes=attrs) is True
    assert qualifies(exp_absent, snap_absent, visitor_attributes={}) is qualifies(
        exp_any, snap_any, visitor_attributes={}
    )


def test_explicit_all_requires_every_referenced_audience_to_match() -> None:
    """The NEW-behavior contrast: pins the ALL/ANY boundary explicitly using
    purely generic audiences (no exclusion rule involved)."""
    snap, exp = _two_generic_audience_experience(matching_options="all")

    # Only one of the two referenced audiences matches -> ALL fails.
    assert qualifies(exp, snap, visitor_attributes={_AUD_1_KEY: _AUD_1_VALUE}) is False

    # Both referenced audiences match -> ALL passes.
    assert (
        qualifies(
            exp,
            snap,
            visitor_attributes={_AUD_1_KEY: _AUD_1_VALUE, _AUD_2_KEY: _AUD_2_VALUE},
        )
        is True
    )


# ---------------------------------------------------------------------------
# Group 3 -- multi-rule-element guard: mixed tree falls through unchanged
# ---------------------------------------------------------------------------


def _two_element_and_tree() -> Dict[str, Any]:
    """Two generic rules ANDed together (2 AND blocks under 1 OR branch) --
    the sanctioned substitute for a genuinely mixed generic+exclusion tree
    (see module docstring). Mirrors ``tests/test_rules.py``'s
    ``test_and_requires_all_branches`` shape and the PHP precedent's
    ``browser``/``country`` vectors verbatim.
    """
    return {
        "OR": [
            {
                "AND": [
                    {"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "browser", "value": "chrome"}]},
                    {"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "country", "value": "US"}]},
                ]
            }
        ]
    }


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"browser": "chrome", "country": "US"}, True),
        ({"browser": "chrome", "country": "DE"}, False),
    ],
    ids=["both_match_and_satisfied", "one_mismatches_and_fails"],
)
def test_multi_rule_element_tree_never_mistaken_for_sole_exclusion_and_falls_through(
    data: Mapping[str, Any], expected: bool
) -> None:
    rules_tree = _two_element_and_tree()

    # Structural guard: a tree with 2 AND blocks (>1 rule element) is never
    # "sole" -- `_sole_rule_item` returns None regardless of the item shapes.
    assert rules._sole_rule_item(rules_tree) is None

    audience = {"id": "aud-mixed", "key": "aud-mixed", "rules": rules_tree}
    experience = {"id": "e1", "key": "exp", "audiences": ["aud-mixed"], "variations": []}
    snap = _snapshot([experience], [audience])

    result = qualifies(experience, snap, visitor_attributes=data)

    # Falls through UNCHANGED to the generic is_rule_matched walk: qualifies()
    # must agree bit-for-bit with a direct is_rule_matched() call on the exact
    # same tree/data (proving no seam divergence), and both equal `expected`.
    assert result == is_rule_matched(data, rules_tree) == expected
