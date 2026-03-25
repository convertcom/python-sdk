from __future__ import annotations

import re
from typing import Any

from .object_utils import object_not_empty
from .string_utils import is_numeric, to_number


def _apply_negation(value: bool, negation: bool = False) -> bool:
    return not value if negation else value


def _normalize_js_comparison_types(
    value: str | int | float, test_against: str | int | float
) -> tuple[Any, Any, str, str]:
    left = to_number(value) if is_numeric(value) else value
    right = to_number(test_against) if is_numeric(test_against) else test_against

    left_type = "number" if isinstance(left, (int, float)) and not isinstance(left, bool) else type(left).__name__
    right_type = (
        "number"
        if isinstance(right, (int, float)) and not isinstance(right, bool)
        else type(right).__name__
    )
    return left, right, left_type, right_type


def equals(value: Any, test_against: Any, negation: bool = False) -> bool:
    if isinstance(value, list):
        return _apply_negation(test_against in value, negation)
    if object_not_empty(value):
        return _apply_negation(
            str(test_against) in [str(key) for key in value.keys()],
            negation,
        )
    left = str(value).lower()
    right = str(test_against).lower()
    return _apply_negation(left == right, negation)


def equals_number(value: Any, test_against: Any, negation: bool = False) -> bool:
    return equals(value, test_against, negation)


def matches(value: Any, test_against: Any, negation: bool = False) -> bool:
    return equals(value, test_against, negation)


def less(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left, right, left_type, right_type = _normalize_js_comparison_types(
        value, test_against
    )
    if left_type != right_type:
        return False
    return _apply_negation(left < right, negation)


def less_equal(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left, right, left_type, right_type = _normalize_js_comparison_types(
        value, test_against
    )
    if left_type != right_type:
        return False
    return _apply_negation(left <= right, negation)


def contains(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left = str(value).lower()
    right = str(test_against).lower()
    if right.strip() == "":
        return _apply_negation(True, negation)
    return _apply_negation(right in left, negation)


def is_in(
    values: str | int | float,
    test_against: list[str | int | float] | str,
    negation: bool = False,
    splitter: str = "|",
) -> bool:
    matched_values = [str(item) for item in str(values).split(splitter)]
    if isinstance(test_against, str):
        candidates: list[Any] = test_against.split(splitter)
    elif isinstance(test_against, list):
        candidates = test_against
    else:
        candidates = []
    normalized_candidates = [str(item).lower() for item in candidates]
    for item in matched_values:
        if item in normalized_candidates:
            return _apply_negation(True, negation)
    return _apply_negation(False, negation)


def starts_with(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left = str(value).lower()
    right = str(test_against).lower()
    return _apply_negation(left.startswith(right), negation)


def ends_with(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left = str(value).lower()
    right = str(test_against).lower()
    return _apply_negation(left.endswith(right), negation)


def regex_matches(
    value: str | int | float, test_against: str | int | float, negation: bool = False
) -> bool:
    left = str(value).lower()
    pattern = str(test_against)
    try:
        matched = re.search(pattern, left, re.IGNORECASE) is not None
    except re.error:
        matched = False
    return _apply_negation(matched, negation)


DEFAULT_COMPARISON_PROCESSOR = {
    "contains": contains,
    "endsWith": ends_with,
    "equals": equals,
    "equalsNumber": equals_number,
    "isIn": is_in,
    "less": less,
    "lessEqual": less_equal,
    "matches": matches,
    "regexMatches": regex_matches,
    "startsWith": starts_with,
}
