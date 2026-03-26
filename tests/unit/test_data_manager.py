from convertcom_sdk.enums import BucketingError


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
