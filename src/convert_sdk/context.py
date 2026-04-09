"""Per-visitor context foundation for reusable SDK behavior."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .domain.config_snapshot import ConfigSnapshot
from .domain.context_state import ContextState
from .domain.results import ConversionResult, ExperienceResult, FeatureResult
from .evaluation.experiences import evaluate_experience, evaluate_experiences
from .evaluation.features import evaluate_feature, evaluate_features
from .tracking.conversions import track_conversion as create_conversion_result


class Context:
    """Visitor-scoped SDK state that later evaluation stories will consume."""

    def __init__(
        self,
        snapshot: ConfigSnapshot,
        state: ContextState,
        *,
        default_environment: Optional[str] = None,
    ) -> None:
        self._snapshot = snapshot
        self._state = state
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

    def track_conversion(self, goal_key: str) -> ConversionResult:
        """Create a typed conversion event for the current visitor context."""

        if not isinstance(goal_key, str) or not goal_key.strip():
            raise ValueError("goal_key is required")

        return create_conversion_result(
            self._snapshot,
            visitor_id=self.visitor_id,
            goal_key=goal_key,
        )

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
