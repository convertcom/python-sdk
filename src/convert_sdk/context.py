"""Per-visitor context foundation for reusable SDK behavior."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .domain.config_snapshot import ConfigSnapshot
from .domain.context_state import ContextState
from .domain.results import (
    ConversionResult,
    ExperienceResult,
    FeatureResult,
    TrackingFlushResult,
)
from .evaluation.experiences import evaluate_experience, evaluate_experiences
from .evaluation.features import evaluate_feature, evaluate_features
from .tracking.conversions import (
    build_conversion_result,
    normalize_conversion_data,
    resolve_goal,
)
from .tracking.queue import TrackingQueue


class Context:
    """Visitor-scoped SDK state that later evaluation stories will consume."""

    def __init__(
        self,
        snapshot: ConfigSnapshot,
        state: ContextState,
        *,
        tracking_queue: TrackingQueue,
        default_environment: Optional[str] = None,
    ) -> None:
        self._snapshot = snapshot
        self._state = state
        self._tracking_queue = tracking_queue
        self._default_environment = default_environment

    @property
    def visitor_id(self) -> str:
        """Return the unique visitor identifier associated with this context."""

        return self._state.visitor_id

    @property
    def visitor_attributes(self) -> Mapping[str, Any]:
        """Return the stored immutable visitor attributes for this context."""

        return self._state.visitor_attributes

    def _resolve_visitor_attributes(
        self,
        request_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Merge stored visitor attributes with request-scoped overrides."""

        return self._state.resolve_visitor_attributes(request_attributes)

    def run_experience(
        self,
        experience_key: str,
        *,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> ExperienceResult | None:
        """Evaluate a single experience locally for this visitor."""

        if not isinstance(experience_key, str) or not experience_key.strip():
            raise ValueError("experience_key is required")

        return evaluate_experience(
            self._snapshot,
            experience_key=experience_key,
            visitor_id=self.visitor_id,
            visitor_attributes=self._resolve_visitor_attributes(visitor_attributes),
            location_attributes=self._resolve_location_attributes(location_attributes),
            environment=environment or self._default_environment,
        )

    def run_experiences(
        self,
        *,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> list[ExperienceResult]:
        """Evaluate all applicable experiences locally for this visitor."""

        return evaluate_experiences(
            self._snapshot,
            visitor_id=self.visitor_id,
            visitor_attributes=self._resolve_visitor_attributes(visitor_attributes),
            location_attributes=self._resolve_location_attributes(location_attributes),
            environment=environment or self._default_environment,
        )

    def run_feature(
        self,
        feature_key: str,
        *,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        environment: Optional[str] = None,
        type_cast: bool = True,
    ) -> FeatureResult | None:
        """Resolve a single feature locally for this visitor."""

        if not isinstance(feature_key, str) or not feature_key.strip():
            raise ValueError("feature_key is required")

        return evaluate_feature(
            self._snapshot,
            feature_key=feature_key,
            visitor_id=self.visitor_id,
            visitor_attributes=self._resolve_visitor_attributes(visitor_attributes),
            location_attributes=self._resolve_location_attributes(location_attributes),
            environment=environment or self._default_environment,
            type_cast=type_cast,
        )

    def run_features(
        self,
        *,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        environment: Optional[str] = None,
        type_cast: bool = True,
    ) -> list[FeatureResult]:
        """Resolve all applicable features locally for this visitor."""

        return evaluate_features(
            self._snapshot,
            visitor_id=self.visitor_id,
            visitor_attributes=self._resolve_visitor_attributes(visitor_attributes),
            location_attributes=self._resolve_location_attributes(location_attributes),
            environment=environment or self._default_environment,
            type_cast=type_cast,
        )

    def track_conversion(
        self,
        goal_key: str,
        *,
        conversion_data: Optional[Mapping[str, Any]] = None,
        force_multiple_transactions: bool = False,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        environment: Optional[str] = None,
    ) -> ConversionResult:
        """Queue typed conversion events for the current visitor context."""

        if not isinstance(goal_key, str) or not goal_key.strip():
            raise ValueError("goal_key is required")
        if not isinstance(force_multiple_transactions, bool):
            raise TypeError("force_multiple_transactions must be a boolean")

        normalized_conversion_data = normalize_conversion_data(conversion_data)
        goal = resolve_goal(self._snapshot, goal_key)
        dedupe_key = (self.visitor_id, str(goal.get("id", goal_key)))
        decision = self._tracking_queue.plan_conversion(
            visitor_id=self.visitor_id,
            goal_id=dedupe_key[1],
            has_conversion_data=bool(normalized_conversion_data),
            allow_repeat_reporting=force_multiple_transactions,
        )
        if decision.duplicate_prevented:
            return ConversionResult(duplicate_prevented=True)

        result = build_conversion_result(
            self._snapshot,
            visitor_id=self.visitor_id,
            goal=goal,
            goal_key=goal_key,
            normalized_conversion_data=normalized_conversion_data,
            visitor_attributes=self._resolve_visitor_attributes(visitor_attributes),
            location_attributes=self._resolve_location_attributes(location_attributes),
            environment=environment or self._default_environment,
            include_base_conversion=decision.should_enqueue_conversion,
            include_transaction_event=decision.should_enqueue_transaction,
        )
        queued_event_count = self._tracking_queue.enqueue(
            result.events,
            mark_tracked_goal=dedupe_key if decision.should_enqueue_conversion else None,
        )
        return ConversionResult(
            events=result.events,
            duplicate_prevented=False,
            queued_event_count=queued_event_count,
        )

    def release_queues(self, reason: Optional[str] = None) -> TrackingFlushResult:
        """Explicitly flush queued tracking events through the transport."""

        return self._tracking_queue.release(reason)

    def _resolve_location_attributes(
        self,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Validate request-scoped location attributes for evaluation."""

        if location_attributes is None:
            return {}
        if not isinstance(location_attributes, Mapping):
            raise TypeError("location_attributes must be a mapping")
        return location_attributes

    def __repr__(self) -> str:
        return f"Context(visitor_id={self.visitor_id!r})"
