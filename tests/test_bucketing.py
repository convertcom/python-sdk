"""Unit tests for the evaluation bucketing primitives (Story 1.4, SDK-1).

Covers the pure-Python MurmurHash3-32 edge cases and the JS-parity bucket
selection helpers (``getValueVisitorBased`` / ``selectBucket`` equivalents).
"""

from convert_sdk.evaluation.bucketing import (
    get_bucket_value_for_visitor,
    murmurhash3_32,
    select_bucket,
)


# --- murmurhash3_32 edge cases ------------------------------------------------


def test_empty_string_hash_is_seed_dependent():
    # Empty string with default seed 9999 (JS reference value).
    assert murmurhash3_32("") == 3523940263


def test_unicode_string_hashes_without_error():
    # 用户123 — multi-byte unicode handled via UTF-8 byte encoding (matching npm
    # murmurhash TextEncoder and PHP SDK unpack('C*')).
    assert murmurhash3_32("用户123") == 3859151469


def test_large_seed_is_supported():
    # Non-default large seed must not overflow into a negative or >32-bit value.
    result = murmurhash3_32("test_visitor", 12345)
    assert 0 <= result < 2**32
    assert result == 2447228397


def test_same_input_is_deterministic():
    assert murmurhash3_32("visitor-1", 9999) == murmurhash3_32("visitor-1", 9999)


def test_composite_experience_visitor_key():
    # Bucketing composes f"{experience_id}{visitor_id}" — JS reference value.
    assert murmurhash3_32("e1visitor-1", 9999) == 3363324936


# --- get_bucket_value_for_visitor (getValueVisitorBased parity) ---------------


def test_bucket_value_in_traffic_range():
    value = get_bucket_value_for_visitor("visitor-1", experience_id="e1")
    assert 0 <= value < 10000
    assert isinstance(value, int)


def test_bucket_value_is_deterministic():
    a = get_bucket_value_for_visitor("visitor-42", experience_id="e1")
    b = get_bucket_value_for_visitor("visitor-42", experience_id="e1")
    assert a == b


def test_bucket_value_matches_js_formula():
    # JS: int((hash / 4294967296) * 10000); hash of "e1visitor-1" = 3363324936.
    expected = int((3363324936 / 4294967296) * 10000)
    assert get_bucket_value_for_visitor("visitor-1", experience_id="e1") == expected


# --- select_bucket (selectBucket parity) --------------------------------------


def test_select_bucket_picks_first_cumulative_match():
    # buckets values are percentages; JS multiplies by 100 cumulatively.
    buckets = {"v1": 50.0, "v2": 50.0}
    # value 0 -> first bucket (cumulative 5000).
    assert select_bucket(buckets, 0) == "v1"
    # value 4999 still within first bucket.
    assert select_bucket(buckets, 4999) == "v1"
    # value 5000 -> second bucket.
    assert select_bucket(buckets, 5000) == "v2"


def test_select_bucket_returns_none_when_value_beyond_range():
    buckets = {"v1": 50.0, "v2": 50.0}
    assert select_bucket(buckets, 10000) is None


def test_select_bucket_empty_returns_none():
    assert select_bucket({}, 0) is None
