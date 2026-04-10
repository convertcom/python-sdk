"""Tracking payload serialization utilities."""

from __future__ import annotations

from typing import Any, Iterable

from ..domain.results import ConversionEvent


DEFAULT_TRACKING_SOURCE = "python-sdk"


def _serialize_goal_data(event: ConversionEvent) -> list[dict[str, Any]]:
    goal_data: list[dict[str, Any]] = []
    for key, value in event.conversion_data.items():
        serialized_value = list(value) if isinstance(value, tuple) else value
        goal_data.append({"key": key, "value": serialized_value})
    return goal_data


def _serialize_event(event: ConversionEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"goalId": event.goal_id}
    if event.conversion_data:
        data["goalData"] = _serialize_goal_data(event)
    if event.bucketing_data:
        data["bucketingData"] = dict(event.bucketing_data)
    return {"eventType": event.event_type, "data": data}


def serialize_tracking_payload(
    events: Iterable[ConversionEvent],
    *,
    source: str = DEFAULT_TRACKING_SOURCE,
    enrich_data: bool = True,
) -> dict[str, Any]:
    """Serialize conversion events into the Convert tracking payload shape."""

    event_list = list(events)
    if not event_list:
        raise ValueError("at least one conversion event is required")

    first = event_list[0]
    payload: dict[str, Any] = {
        "source": source,
        "enrichData": enrich_data,
        "visitors": [],
    }
    if first.account_id is not None:
        payload["accountId"] = first.account_id
    if first.project_id is not None:
        payload["projectId"] = first.project_id

    visitors: dict[str, dict[str, Any]] = {}
    for event in event_list:
        if event.account_id != first.account_id or event.project_id != first.project_id:
            raise ValueError("all tracking events must share the same account and project")

        visitor = visitors.setdefault(
            event.visitor_id,
            {"visitorId": event.visitor_id, "events": []},
        )
        visitor["events"].append(_serialize_event(event))

    payload["visitors"] = list(visitors.values())
    return payload
