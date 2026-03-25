from convertcom_sdk.utils.string_utils import camel_case, generate_hash, is_numeric, to_number


def test_camel_case_matches_js_behavior():
    assert camel_case("get js condition") == "getJsCondition"


def test_generate_hash_matches_js_murmurhash_outputs():
    assert generate_hash("100123456", 9999) == 2494577814
    assert generate_hash("100123456", 11223344) == 1783836153
    assert generate_hash("100123456", 99887766) == 1036306062
    assert generate_hash("01ABCD", 9999) == 2347149437
    assert generate_hash("exp-101ABCD", 9999) == 2639235140


def test_is_numeric_matches_js_cases():
    assert is_numeric("122.5") is True
    assert is_numeric("1,123.5") is True
    assert is_numeric(".5") is True
    assert is_numeric("orange") is False


def test_to_number_matches_js_comma_behavior():
    assert to_number("122.5") == 122.5
    assert to_number("1,123.5") == 1123.5
    assert to_number("0,5") == 0.5
