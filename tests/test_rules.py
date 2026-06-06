"""Unit tests for MVP audience/location rule evaluation (Story 1.4, SDK-2).

Mirrors the JS SDK rule semantics for the current FullStack config shapes:
nested ``OR / AND / OR_WHEN`` rule sets with ``matching.match_type`` operators,
and the experience-level qualification rule (empty/absent audiences or
locations means unrestricted => match). Normal misses return ``False`` — never
exceptions.
"""

from convert_sdk.evaluation.rules import is_rule_matched, qualifies


# --- is_rule_matched: operator + boolean-tree semantics -----------------------


def _rule(match_type, key, value, negated=False):
    return {
        "OR": [
            {"AND": [{"OR_WHEN": [{"matching": {"match_type": match_type, "negated": negated}, "key": key, "value": value}]}]}
        ]
    }


def test_equals_operator_matches_case_insensitive():
    rule = _rule("equals", "country", "US")
    assert is_rule_matched({"country": "us"}, rule) is True
    assert is_rule_matched({"country": "CA"}, rule) is False


def test_contains_operator():
    rule = _rule("contains", "url", "checkout")
    assert is_rule_matched({"url": "https://shop/CHECKOUT/cart"}, rule) is True
    assert is_rule_matched({"url": "https://shop/home"}, rule) is False


def test_negated_operator_inverts():
    rule = _rule("equals", "country", "US", negated=True)
    assert is_rule_matched({"country": "us"}, rule) is False
    assert is_rule_matched({"country": "ca"}, rule) is True


def test_exists_operator_with_missing_key():
    rule = _rule("exists", "plan", "")
    assert is_rule_matched({"plan": "pro"}, rule) is True
    assert is_rule_matched({"other": "x"}, rule) is False


def test_and_requires_all_branches():
    rule = {
        "OR": [
            {
                "AND": [
                    {"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "country", "value": "US"}]},
                    {"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "plan", "value": "pro"}]},
                ]
            }
        ]
    }
    assert is_rule_matched({"country": "us", "plan": "pro"}, rule) is True
    assert is_rule_matched({"country": "us", "plan": "free"}, rule) is False


def test_missing_data_returns_false_not_exception():
    rule = _rule("equals", "country", "US")
    assert is_rule_matched({}, rule) is False
    assert is_rule_matched(None, rule) is False


# --- qualifies: experience-level audience/location qualification --------------


def _snapshot(audiences=(), experiences=()):
    from convert_sdk.config_loader import load_snapshot

    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": list(experiences),
            "audiences": list(audiences),
        }
    )


def test_experience_with_no_audiences_or_locations_qualifies():
    exp = {"id": "e1", "key": "exp", "variations": []}
    snap = _snapshot(experiences=[exp])
    assert qualifies(exp, snap, visitor_attributes={}, location_attributes={}) is True


def test_audience_match_qualifies():
    aud = {"id": "a1", "key": "aud", "rules": _rule("equals", "country", "US")}
    exp = {"id": "e1", "key": "exp", "audiences": ["a1"], "variations": []}
    snap = _snapshot(audiences=[aud], experiences=[exp])
    assert qualifies(exp, snap, visitor_attributes={"country": "US"}) is True
    assert qualifies(exp, snap, visitor_attributes={"country": "CA"}) is False


def test_site_area_location_match_qualifies():
    exp = {
        "id": "e1",
        "key": "exp",
        "site_area": _rule("contains", "url", "/checkout"),
        "variations": [],
    }
    snap = _snapshot(experiences=[exp])
    assert qualifies(exp, snap, location_attributes={"url": "/checkout/cart"}) is True
    assert qualifies(exp, snap, location_attributes={"url": "/home"}) is False


def test_missing_audience_definition_does_not_qualify_restricted_experience():
    # Experience references an audience id that isn't in the snapshot -> no match.
    exp = {"id": "e1", "key": "exp", "audiences": ["ghost"], "variations": []}
    snap = _snapshot(experiences=[exp])
    assert qualifies(exp, snap, visitor_attributes={"country": "US"}) is False
