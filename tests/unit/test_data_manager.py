from convertcom_sdk.enums import BucketingError
from convertcom_sdk import (
    BucketingManager,
    DataManager,
    DataStoreManager,
    RuleManager,
)


VISITOR_ID = "XXX"


class FakeDataStore:
    def __init__(self) -> None:
        self.data = {}
        self.set_calls = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.set_calls.append((key, value))


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


def test_put_data_enqueues_filtered_segments_for_datastore(config):
    store = FakeDataStore()
    data_store_manager = DataStoreManager(
        {"events": {"batch_size": 10, "release_interval": 50}},
        data_store=store,
    )
    data_manager = DataManager(
        config,
        bucketing_manager=BucketingManager(config),
        rule_manager=RuleManager(config),
        data_store_manager=data_store_manager,
    )

    data_manager.put_data(
        "visitor-1",
        {"segments": {"country": "US", "weather": "rainy"}},
    )

    assert store.set_calls == []
    assert data_manager.get_data("visitor-1") == {
        "segments": {"country": "US", "weather": "rainy"}
    }

    data_store_manager.release_queue("manual")

    assert len(store.set_calls) == 1
    assert store.set_calls[0][1] == {"segments": {"country": "US"}}
