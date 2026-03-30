from convertcom_sdk.enums import BucketingError
from convertcom_sdk import BucketingManager, DataManager, RuleManager


VISITOR_ID = "XXX"


def test_validates_fixture_config(managers, config):
    data_manager = managers["data_manager"]
    assert data_manager.is_valid_config_data(config["data"]) is True


def test_get_bucketing_by_key(managers):
    data_manager = managers["data_manager"]
    variation = data_manager.get_bucketing(
        VISITOR_ID,
        "test-experience-ab-fullstack-2",
        {
            "visitorProperties": {"varName3": "something"},
            "locationProperties": {"url": "https://convert.com/"},
        },
    )
    assert variation["experienceKey"] == "test-experience-ab-fullstack-2"
    assert variation["id"] in {"100299456", "100299457"}


def test_get_bucketing_by_id(managers):
    data_manager = managers["data_manager"]
    variation = data_manager.get_bucketing_by_id(
        VISITOR_ID,
        "100218245",
        {
            "visitorProperties": {"varName3": "something"},
            "locationProperties": {"url": "https://convert.com/"},
        },
    )
    assert variation["experienceId"] == "100218245"


def test_get_entities_helpers(managers):
    data_manager = managers["data_manager"]
    features = data_manager.get_entities(["feature-1", "feature-2"], "features")
    assert [feature["id"] for feature in features] == ["10024", "10025"]

    features_by_id = data_manager.get_entities_by_ids(["10024", "10025"], "features")
    assert [feature["key"] for feature in features_by_id] == ["feature-1", "feature-2"]


def test_bucketing_returns_none_when_rules_do_not_match(managers):
    data_manager = managers["data_manager"]
    variation = data_manager.get_bucketing(
        VISITOR_ID,
        "test-experience-ab-fullstack-2",
        {
            "visitorProperties": {"varName3": "different"},
            "locationProperties": {"url": "https://example.com/"},
        },
    )
    assert variation is None


def test_bucketing_error_when_variations_missing(managers):
    data_manager = managers["data_manager"]
    variation = data_manager.get_bucketing(
        VISITOR_ID,
        "test-experience-ab-fullstack-4",
        {
            "visitorProperties": {"varName3": "something"},
            "locationProperties": {"url": "https://convert.com/"},
        },
    )
    assert variation == BucketingError.VARIAION_NOT_DECIDED


def test_data_manager_eviction_respects_cache_limit(config):
    hardened_config = {
        **config,
        "cache": {"max_entries": 1},
    }
    data_manager = DataManager(
        hardened_config,
        bucketing_manager=BucketingManager(hardened_config),
        rule_manager=RuleManager(hardened_config),
    )

    data_manager.put_data("visitor-1", {"segments": {"country": "US"}})
    data_manager.put_data("visitor-2", {"segments": {"country": "GB"}})

    assert data_manager.get_data("visitor-1") is None
    assert data_manager.get_data("visitor-2") == {"segments": {"country": "GB"}}


def test_data_store_release_queue_passthrough():
    released = []

    class FakeDataStore:
        def get(self, key):  # noqa: ARG002
            return None

        def set(self, key, data):  # noqa: ARG002
            return None

        def release_queue(self, reason=None):
            released.append(reason)

    from convertcom_sdk.data import DataStoreManager

    manager = DataStoreManager(data_store=FakeDataStore())

    manager.release_queue("manual")

    assert released == ["manual"]
