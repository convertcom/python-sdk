"""Conversion-tracking primitives for visitor contexts."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from ..domain.config_snapshot import ConfigSnapshot
from ..domain.results import (
    ConversionEvent,
    ConversionResult,
    freeze_bucketing_data,
    freeze_conversion_data,
)
from ..errors import ConversionDataError, GoalNotFoundError
from ..evaluation.experiences import evaluate_experiences


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def resolve_goal(
    snapshot: ConfigSnapshot,
    goal_key: str,
) -> Mapping[str, object]:
    goal = snapshot.goals_by_key.get(goal_key)
    if goal is None:
        raise GoalNotFoundError(
            f"Unknown goal_key {goal_key!r} for the current config snapshot"
        )
    return goal


def _normalize_conversion_value(value: Any) -> Any:
    if isinstance(value, bool):
        raise ConversionDataError(
            "conversion_data values must be int, float, str, or a sequence of strings"
        )
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ConversionDataError(
                    "conversion_data sequence values must contain only strings"
                )
            normalized.append(item)
        return tuple(normalized)
    raise ConversionDataError(
        "conversion_data values must be int, float, str, or a sequence of strings"
    )


def normalize_conversion_data(
    conversion_data: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if conversion_data is None:
        return freeze_conversion_data(None)
    if not isinstance(conversion_data, Mapping):
        raise ConversionDataError("conversion_data must be a mapping")

    normalized: dict[str, Any] = {}
    for key, value in conversion_data.items():
        key_text = str(key).strip()
        if not key_text:
            raise ConversionDataError("conversion_data keys must be non-empty strings")
        normalized[key_text] = _normalize_conversion_value(value)
    return freeze_conversion_data(normalized)


def _build_bucketing_data(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: Optional[str],
) -> Mapping[str, str]:
    results = evaluate_experiences(
        snapshot,
        visitor_id=visitor_id,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
    )
    return freeze_bucketing_data(
        {result.experience_id: result.variation_id for result in results}
    )


def _build_event(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    goal: Mapping[str, object],
    goal_key: str,
    conversion_data: Mapping[str, Any],
    bucketing_data: Mapping[str, str],
) -> ConversionEvent:
    return ConversionEvent(
        visitor_id=visitor_id,
        goal_id=str(goal.get("id", goal_key)),
        goal_key=str(goal.get("key", goal_key)),
        goal_name=_optional_text(goal.get("name")),
        account_id=snapshot.account_id,
        project_id=snapshot.project_id,
        conversion_data=conversion_data,
        bucketing_data=bucketing_data,
    )


def build_conversion_result(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    goal: Mapping[str, object],
    goal_key: str,
    normalized_conversion_data: Mapping[str, Any],
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
    environment: Optional[str] = None,
    include_base_conversion: bool = True,
    include_transaction_event: bool = True,
) -> ConversionResult:
    """Create typed conversion events for a visitor-scoped goal trigger."""

    bucketing_data = _build_bucketing_data(
        snapshot,
        visitor_id=visitor_id,
        visitor_attributes=visitor_attributes or {},
        location_attributes=location_attributes or {},
        environment=environment,
    )

    events: list[ConversionEvent] = []
    if include_base_conversion:
        events.append(
            _build_event(
                snapshot,
                visitor_id=visitor_id,
                goal=goal,
                goal_key=goal_key,
                conversion_data=freeze_conversion_data(None),
                bucketing_data=bucketing_data,
            )
        )
    if normalized_conversion_data and include_transaction_event:
        events.append(
            _build_event(
                snapshot,
                visitor_id=visitor_id,
                goal=goal,
                goal_key=goal_key,
                conversion_data=normalized_conversion_data,
                bucketing_data=bucketing_data,
            )
        )

    return ConversionResult(events=tuple(events))


def track_conversion(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    goal_key: str,
    conversion_data: Optional[Mapping[str, Any]] = None,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
    environment: Optional[str] = None,
) -> ConversionResult:
    """Create a typed conversion result for a visitor-scoped goal trigger."""

    goal = resolve_goal(snapshot, goal_key)
    normalized_conversion_data = normalize_conversion_data(conversion_data)
    return build_conversion_result(
        snapshot,
        visitor_id=visitor_id,
        goal=goal,
        goal_key=goal_key,
        normalized_conversion_data=normalized_conversion_data,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
    )
