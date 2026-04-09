from __future__ import annotations

from convert_sdk.tracking.payloads import serialize_tracking_payload

from test_experience_evaluation import build_context


def test_serialize_tracking_payload_matches_expected_shape() -> None:
    context = build_context("visitor-123", {"tier": "premium"})
    result = context.track_conversion(
        "purchase",
        conversion_data={"amount": 10.3, "productsCount": 2},
        location_attributes={"path": "/checkout"},
    )

    payload = serialize_tracking_payload([result.event])

    assert payload == {
        "source": "python-sdk",
        "enrichData": True,
        "accountId": "1001",
        "projectId": "2002",
        "visitors": [
            {
                "visitorId": "visitor-123",
                "events": [
                    {
                        "eventType": "conversion",
                        "data": {
                            "goalId": "goal-1",
                            "goalData": [
                                {"key": "amount", "value": 10.3},
                                {"key": "productsCount", "value": 2},
                            ],
                            "bucketingData": dict(result.event.bucketing_data),
                        },
                    }
                ],
            }
        ],
    }


def test_serialize_tracking_payload_groups_events_by_visitor() -> None:
    context = build_context("visitor-123", {"tier": "premium"})
    first = context.track_conversion("purchase")
    second = context.track_conversion(
        "purchase",
        conversion_data={"transactionId": "txn-1"},
    )

    payload = serialize_tracking_payload([first.event, second.event])

    assert len(payload["visitors"]) == 1
    assert payload["visitors"][0]["visitorId"] == "visitor-123"
    assert len(payload["visitors"][0]["events"]) == 2
