import pytest

from convertcom_sdk.utils.comparisons import DEFAULT_COMPARISON_PROCESSOR as comparisons


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("equals", (123, 123), True),
        ("equals", (123, 123, True), False),
        ("equals", ("value", 123), False),
        ("equals", ("value", 123, True), True),
        ("less", ("122.5", 123), True),
        ("less", ("1,123.5", 123, True), True),
        ("less", (-111, 123), True),
        ("less", (123, 123, True), True),
        ("less", ("abcde", "axyz"), True),
        ("less", ("orange", 4), False),
        ("lessEqual", (4, 4), True),
        ("lessEqual", (4, "orange"), False),
        ("lessEqual", (123, 4, True), True),
        ("lessEqual", ("abcde", "axyz"), True),
        ("lessEqual", ("1,123.5", 1123.5, True), False),
        ("contains", ("abcde", "a"), True),
        ("contains", (23, 12345, True), True),
        ("contains", ("abcde", ""), True),
        ("isIn", ("a", "a|b|c|d|e"), True),
        ("isIn", ("a|c", "a|b|c|d|e"), True),
        ("isIn", ("orange", ["ab", "cd", "ef"]), False),
        ("isIn", ("a,c", "a,b,c,d,e", False, ","), True),
        ("startsWith", (12345678, 12), True),
        ("startsWith", ("orange is fruit`", "is", True), True),
        ("endsWith", (12345678, 45678), True),
        ("endsWith", ("orange is fruit", "fruit"), True),
        ("regexMatches", ("orange", r"\w+"), True),
        ("regexMatches", ("An APPle!", r"\d+"), False),
        ("regexMatches", (111222333, r"\d+"), True),
    ],
)
def test_comparisons_match_js_behavior(name, args, expected):
    assert comparisons[name](*args) is expected
