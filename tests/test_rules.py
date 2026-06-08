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


# --- isIn operator -----------------------------------------------------------


def test_is_in_number_same_value_hit():
    """isIn(23, 23) -> True (PHP test case: testIsInReturnsTrueForSameNumber)."""
    rule = _rule("isIn", "score", 23)
    assert is_rule_matched({"score": "23"}, rule) is True


def test_is_in_pipe_delimited_string_hit():
    """isIn('a', 'a|b|c|d|e') -> True (PHP testIsInReturnsTrueForDelimitedString)."""
    rule = _rule("isIn", "tier", "a|b|c|d|e")
    assert is_rule_matched({"tier": "a"}, rule) is True


def test_is_in_pipe_delimited_string_negated_false():
    """isIn('a', 'a|b|c|d|e', negated=True) -> False."""
    rule = _rule("isIn", "tier", "a|b|c|d|e", negated=True)
    assert is_rule_matched({"tier": "a"}, rule) is False


def test_is_in_multi_value_pipe_delimited_hit():
    """Visitor value 'a|c' split by '|': 'a' is in 'a|b|c|d|e' -> True."""
    rule = _rule("isIn", "tier", "a|b|c|d|e")
    assert is_rule_matched({"tier": "a|c"}, rule) is True


def test_is_in_against_list_miss():
    """isIn('orange', ['ab', 'cd', 'ef']) -> False."""
    rule = _rule("isIn", "code", ["ab", "cd", "ef"])
    assert is_rule_matched({"code": "orange"}, rule) is False


def test_is_in_against_list_negated_hit():
    """isIn('orange', ['ab', 'cd', 'ef'], negated=True) -> True."""
    rule = _rule("isIn", "code", ["ab", "cd", "ef"], negated=True)
    assert is_rule_matched({"code": "orange"}, rule) is True


def test_is_in_multi_value_against_list_hit():
    """isIn('ab|ef', ['ab', 'cd', 'ef']) -> True ('ab' found in list)."""
    rule = _rule("isIn", "code", ["ab", "cd", "ef"])
    assert is_rule_matched({"code": "ab|ef"}, rule) is True


def test_is_in_empty_value_against_empty_list_miss():
    """isIn('', []) -> False (empty list, '' vs [] -> no match)."""
    rule = _rule("isIn", "code", [])
    assert is_rule_matched({"code": ""}, rule) is False


def test_is_in_number_in_list_hit():
    """isIn(456, [123, 456, 789]) -> True (number coerced to string)."""
    rule = _rule("isIn", "score", [123, 456, 789])
    assert is_rule_matched({"score": "456"}, rule) is True


def test_is_in_missing_key_returns_false():
    """Missing key -> False (operator needs a value)."""
    rule = _rule("isIn", "plan", "free|pro|enterprise")
    assert is_rule_matched({}, rule) is False
    assert is_rule_matched(None, rule) is False


# --- regexMatches operator ---------------------------------------------------


def test_regex_matches_word_characters_hit():
    """regexMatches('orange', '\\w+') -> True."""
    rule = _rule("regexMatches", "label", r"\w+")
    assert is_rule_matched({"label": "orange"}, rule) is True


def test_regex_matches_word_characters_with_exclamation():
    """regexMatches('An APPle!', '\\w+') -> True (word chars present)."""
    rule = _rule("regexMatches", "label", r"\w+")
    assert is_rule_matched({"label": "An APPle!"}, rule) is True


def test_regex_matches_digits_hit():
    """regexMatches(111222333, '\\d+') -> True."""
    rule = _rule("regexMatches", "code", r"\d+")
    assert is_rule_matched({"code": "111222333"}, rule) is True


def test_regex_matches_digits_negated_false():
    """regexMatches(111222333, '\\d+', negated=True) -> False."""
    rule = _rule("regexMatches", "code", r"\d+", negated=True)
    assert is_rule_matched({"code": "111222333"}, rule) is False


def test_regex_matches_email_valid():
    """regexMatches valid email against email pattern -> True."""
    pattern = r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$"
    rule = _rule("regexMatches", "email", pattern)
    assert is_rule_matched({"email": "test@email.com"}, rule) is True


def test_regex_matches_complex_email_valid():
    """regexMatches complex email address against email pattern -> True."""
    pattern = r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$"
    rule = _rule("regexMatches", "email", pattern)
    assert is_rule_matched({"email": "more.complex.e-mail123@subdomain.email.com"}, rule) is True


def test_regex_matches_not_an_email_miss():
    """regexMatches 'Not an email' against email pattern -> False."""
    pattern = r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$"
    rule = _rule("regexMatches", "email", pattern)
    assert is_rule_matched({"email": "Not an email"}, rule) is False


def test_regex_matches_invalid_pattern_returns_false_not_exception():
    """Invalid regex pattern must return False, never raise."""
    rule = _rule("regexMatches", "path", "/?wwww[invalid")
    assert is_rule_matched({"path": "/?wwww"}, rule) is False


def test_regex_matches_missing_key_returns_false():
    """Missing key -> False."""
    rule = _rule("regexMatches", "label", r"\w+")
    assert is_rule_matched({}, rule) is False


def test_regex_matches_case_insensitive():
    """regexMatches is case-insensitive (value is lowercased, regex has IGNORECASE)."""
    rule = _rule("regexMatches", "brand", "^CONVERT")
    assert is_rule_matched({"brand": "Convert Experiences"}, rule) is True
