VISITOR_ID = "XXX"


def test_feature_queries(managers, config):
    feature_manager = managers["feature_manager"]
    assert feature_manager.get_list() == config["data"]["features"]
    assert feature_manager.get_list_as_object("id")["10024"]["key"] == "feature-1"
    assert feature_manager.get_feature("feature-1")["id"] == "10024"
    assert feature_manager.get_feature_by_id("10024")["key"] == "feature-1"
    assert feature_manager.get_feature_variable_type("feature-1", "enabled") == "boolean"
    assert feature_manager.get_feature_variable_type_by_id("10024", "enabled") == "boolean"
    assert feature_manager.is_feature_declared("feature-1") is True


def test_run_feature_and_feature_enabled(managers):
    feature_manager = managers["feature_manager"]
    attributes = {
        "visitorProperties": {"varName3": "something"},
        "locationProperties": {"url": "https://convert.com/"},
    }
    features = feature_manager.run_feature(VISITOR_ID, "feature-1", attributes)
    assert isinstance(features, list)
    assert len(features) == 2
    assert {feature["id"] for feature in features} == {"10024"}
    assert feature_manager.is_feature_enabled(VISITOR_ID, "feature-1", attributes) is True


def test_run_feature_by_id_and_run_features(managers):
    feature_manager = managers["feature_manager"]
    attributes = {
        "visitorProperties": {"varName3": "something"},
        "locationProperties": {"url": "https://convert.com/"},
        "typeCasting": True,
    }
    features = feature_manager.run_feature_by_id(VISITOR_ID, "10024", attributes)
    assert isinstance(features, list)
    assert len(features) == 2

    all_features = feature_manager.run_features(
        VISITOR_ID,
        attributes,
        {
            "features": ["feature-1", "feature-2", "not-attached-feature-3"],
            "experiences": [
                "test-experience-ab-fullstack-2",
                "test-experience-ab-fullstack-3",
            ],
        },
    )
    assert len(all_features) == 3
    assert {feature["id"] for feature in all_features}.issubset(
        {"10024", "10025", "10026"}
    )


def test_feature_cast_type(managers):
    feature_manager = managers["feature_manager"]
    assert isinstance(feature_manager.cast_type("123", "integer"), int)
    assert isinstance(feature_manager.cast_type(123, "string"), str)
    assert isinstance(feature_manager.cast_type("1.23", "float"), float)
    assert isinstance(feature_manager.cast_type("false", "boolean"), bool)
