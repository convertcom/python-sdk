VISITOR_ID = "XXX"


def test_put_and_get_segments(managers):
    segments_manager = managers["segments_manager"]
    segments_manager.put_segments(
        VISITOR_ID,
        {
            "country": "US",
            "browser": "chrome",
            "varName3": "something",
        },
    )
    assert segments_manager.get_segments(VISITOR_ID) == {
        "country": "US",
        "browser": "chrome",
    }


def test_select_custom_segments(managers):
    segments_manager = managers["segments_manager"]
    segments_manager.select_custom_segments(
        VISITOR_ID,
        ["test-segments-1"],
        {"enabled": True},
    )
    segments = segments_manager.get_segments(VISITOR_ID)
    assert segments["customSegments"] == ["200299434"]
