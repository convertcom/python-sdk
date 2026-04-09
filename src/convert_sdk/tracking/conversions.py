"""Conversion-tracking primitives for visitor contexts."""

from __future__ import annotations

from typing import Mapping

from ..domain.config_snapshot import ConfigSnapshot
from ..domain.results import ConversionEvent, ConversionResult
from ..errors import GoalNotFoundError


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _resolve_goal(
    snapshot: ConfigSnapshot,
    goal_key: str,
) -> Mapping[str, object]:
    goal = snapshot.goals_by_key.get(goal_key)
    if goal is None:
        raise GoalNotFoundError(
            f"Unknown goal_key {goal_key!r} for the current config snapshot"
        )
    return goal


def track_conversion(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    goal_key: str,
) -> ConversionResult:
    """Create a typed conversion result for a visitor-scoped goal trigger."""

    goal = _resolve_goal(snapshot, goal_key)

    event = ConversionEvent(
        visitor_id=visitor_id,
        goal_id=str(goal.get("id", goal_key)),
        goal_key=str(goal.get("key", goal_key)),
        goal_name=_optional_text(goal.get("name")),
        account_id=snapshot.account_id,
        project_id=snapshot.project_id,
    )
    return ConversionResult(event=event)
