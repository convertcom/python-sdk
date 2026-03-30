from __future__ import annotations

from convertcom_sdk import ConvertSDK, EntityType
from convertcom_sdk.utils import HttpResponse


def make_request_sender(requests):
    def sender(*, method, base_url, route, headers, data, **kwargs):
        requests.append(
            {
                "method": method,
                "base_url": base_url,
                "route": route,
                "headers": headers,
                "data": data,
                "kwargs": kwargs,
            }
        )
        return HttpResponse(
            status=200,
            data={},
            headers={"Content-Type": "application/json"},
        )

    return sender


def test_context_runs_experience_and_features(config):
    requests = []
    sdk = ConvertSDK(config, request_sender=make_request_sender(requests))
    context = sdk.create_context("XXX", {"browser": "chrome", "country": "US"})

    variation = context.run_experience(
        "test-experience-ab-fullstack-2",
        {
            "locationProperties": {"url": "https://convert.com/"},
            "visitorProperties": {"varName3": "something"},
        },
    )
    features = context.run_features(
        {
            "locationProperties": {"url": "https://convert.com/"},
            "visitorProperties": {"varName3": "something"},
            "typeCasting": True,
        }
    )

    assert variation["experienceKey"] == "test-experience-ab-fullstack-2"
    assert len(features) >= 2
    context.release_queues("manual")
    assert requests[0]["route"].startswith("/track/")


def test_context_tracks_conversion_and_release_queues(config):
    requests = []
    sdk = ConvertSDK(config, request_sender=make_request_sender(requests))
    context = sdk.create_context("XXX")

    result = context.track_conversion(
        "increase-engagement",
        {
            "ruleData": {"action": "buy"},
            "conversionData": [
                {"key": "amount", "value": 10.3},
                {"key": "productsCount", "value": 2},
            ],
        },
    )
    context.release_queues("manual")

    assert result is True
    assert requests[-1]["route"].startswith("/track/")
    payload = requests[-1]["data"]
    assert payload["visitors"][0]["events"][0]["eventType"] == "conversion"


def test_context_helpers(config):
    sdk = ConvertSDK(config)
    context = sdk.create_context("XXX")

    context.set_default_segments({"country": "UK"})
    context.run_custom_segments("test-segments-1", {"ruleData": {"enabled": True}})
    context.update_visitor_properties("XXX", {"weather": "rainy"})

    assert context.get_config_entity("feature-2", EntityType.FEATURE)["id"] == "10025"
    assert (
        context.get_config_entity_by_id("100299461", EntityType.VARIATION)["key"]
        == "100299461-variation-1"
    )
    assert context.get_visitor_data()["segments"]["weather"] == "rainy"
