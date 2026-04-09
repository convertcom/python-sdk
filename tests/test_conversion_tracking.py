from __future__ import annotations

import pytest

from convert_sdk import (
    ConversionDataError,
    ConversionEvent,
    ConversionResult,
    GoalNotFoundError,
)

from test_experience_evaluation import build_context


def test_track_conversion_returns_a_typed_result_for_a_known_goal() -> None:
    context = build_context("visitor-123", {"tier": "premium"})
    expected_bucketing = {
        evaluation.experience_id: evaluation.variation_id
        for evaluation in context.run_experiences()
    }

    result = context.track_conversion("purchase")

    assert isinstance(result, ConversionResult)
    assert isinstance(result.event, ConversionEvent)
    assert result.queued_event_count == 1
    assert result.duplicate_prevented is False
    assert result.event.event_type == "conversion"
    assert result.event.visitor_id == "visitor-123"
    assert result.event.goal_id == "goal-1"
    assert result.event.goal_key == "purchase"
    assert result.event.account_id == "1001"
    assert result.event.project_id == "2002"
    assert result.event.conversion_data == {}
    assert result.event.bucketing_data == expected_bucketing


def test_track_conversion_carries_conversion_data_and_bucketing_context() -> None:
    context = build_context("visitor-123", {"tier": "premium"})
    expected_bucketing = {
        result.experience_id: result.variation_id
        for result in context.run_experiences(location_attributes={"path": "/checkout"})
    }

    result = context.track_conversion(
        "purchase",
        conversion_data={"amount": 10.3, "productsCount": 2},
        location_attributes={"path": "/checkout"},
    )

    assert result.queued_event_count == 2
    assert len(result.events) == 2
    assert result.events[0].conversion_data == {}
    assert result.event.conversion_data == {
        "amount": 10.3,
        "productsCount": 2,
    }
    assert result.event.bucketing_data == expected_bucketing


def test_track_conversion_raises_a_typed_error_for_unknown_goals() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(GoalNotFoundError, match="missing-goal"):
        context.track_conversion("missing-goal")


def test_track_conversion_requires_a_non_empty_goal_key() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(ValueError, match="goal_key is required"):
        context.track_conversion("")


def test_track_conversion_rejects_invalid_conversion_data() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(ConversionDataError, match="conversion_data must be a mapping"):
        context.track_conversion("purchase", conversion_data=["invalid"])  # type: ignore[arg-type]
