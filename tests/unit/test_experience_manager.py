VISITOR_ID = "XXX"


def test_experience_queries(managers, config):
    experience_manager = managers["experience_manager"]
    assert experience_manager.get_list() == config["data"]["experiences"]
    assert experience_manager.get_experience("test-experience-ab-fullstack-2")["id"] == "100218245"
    assert experience_manager.get_experience_by_id("100218245")["key"] == "test-experience-ab-fullstack-2"


def test_select_variation_and_variations(managers):
    experience_manager = managers["experience_manager"]
    attributes = {
        "visitorProperties": {"varName3": "something"},
        "locationProperties": {"url": "https://convert.com/"},
    }
    variation = experience_manager.select_variation(
        VISITOR_ID,
        "test-experience-ab-fullstack-2",
        attributes,
    )
    assert variation["experienceKey"] == "test-experience-ab-fullstack-2"

    variation_by_id = experience_manager.select_variation_by_id(
        VISITOR_ID,
        "100218245",
        attributes,
    )
    assert variation_by_id["experienceId"] == "100218245"

    variations = experience_manager.select_variations(VISITOR_ID, attributes)
    assert len(variations) == 2
    assert {item["id"] for item in variations}.issubset(
        {"100299456", "100299457", "100299460", "100299461"}
    )


def test_get_variations_by_key_and_id(managers):
    experience_manager = managers["experience_manager"]
    variation = experience_manager.get_variation(
        "test-experience-ab-fullstack-2",
        "100299457-variation-1",
    )
    assert variation["id"] == "100299457"

    variation_by_id = experience_manager.get_variation_by_id(
        "100218245",
        "100299457",
    )
    assert variation_by_id["key"] == "100299457-variation-1"
