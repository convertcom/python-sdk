from __future__ import annotations

import pytest

from convert_sdk import ConversionEvent, ConversionResult, GoalNotFoundError

from test_experience_evaluation import build_context


def test_track_conversion_returns_a_typed_result_for_a_known_goal() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    result = context.track_conversion("purchase")

    assert isinstance(result, ConversionResult)
    assert isinstance(result.event, ConversionEvent)
    assert result.event.event_type == "conversion"
    assert result.event.visitor_id == "visitor-123"
    assert result.event.goal_id == "goal-1"
    assert result.event.goal_key == "purchase"
    assert result.event.account_id == "1001"
    assert result.event.project_id == "2002"


def test_track_conversion_raises_a_typed_error_for_unknown_goals() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(GoalNotFoundError, match="missing-goal"):
        context.track_conversion("missing-goal")


def test_track_conversion_requires_a_non_empty_goal_key() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(ValueError, match="goal_key is required"):
        context.track_conversion("")
