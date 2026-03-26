from convertcom_sdk.bucketing import BucketingManager


TEST_VARIATIONS = {
    "100234567": 10,
    "100234568": 30,
    "100234569": 60,
    "100234570": 0,
}


def test_select_bucket_matches_range_behavior():
    manager = BucketingManager()
    assert manager.select_bucket(TEST_VARIATIONS, 100) == "100234567"
    assert manager.select_bucket(TEST_VARIATIONS, 1500) == "100234568"
    assert manager.select_bucket(TEST_VARIATIONS, 9500) == "100234569"


def test_select_bucket_returns_none_when_not_decided():
    manager = BucketingManager()
    assert manager.select_bucket(
        {"100234567": 0, "100234568": 0, "100234569": 0, "100234570": 0},
        6000,
    ) is None


def test_visitor_value_is_stable():
    manager = BucketingManager()
    assert manager.get_value_visitor_based("100123456") == manager.get_value_visitor_based(
        "100123456"
    )


def test_seed_changes_bucket_value():
    manager = BucketingManager()
    assert manager.get_value_visitor_based("100123456", {"seed": 11223344}) != manager.get_value_visitor_based(
        "100123456", {"seed": 99887766}
    )


def test_bucket_for_visitor_is_stable():
    manager = BucketingManager()
    allocations = {
        manager.get_bucket_for_visitor(TEST_VARIATIONS, "01ABCD").variation_id
        for _ in range(100)
    }
    assert allocations == {
        manager.get_bucket_for_visitor(TEST_VARIATIONS, "01ABCD").variation_id
    }
