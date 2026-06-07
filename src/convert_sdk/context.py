"""Visitor-scoped context and local experience evaluation (Story 1.4).

A :class:`Context` binds a visitor identity and immutable visitor attributes to
the current :class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`, and
exposes the local experience-evaluation surface:

* :meth:`Context.run_experience` — evaluate one experience by key.
* :meth:`Context.run_experiences` — evaluate all applicable experiences.

Both methods read only the immutable snapshot and caller-scoped attributes —
they perform **no network I/O**, no config refresh, and no tracking/persistence
side effects (those land in later stories). Request-time attribute overlays are
ephemeral to a single call and never mutate the context's stored visitor state
or the shared snapshot.

Story 1.1 froze ``from convert_sdk import Context`` as an empty placeholder;
this story implements the first real per-visitor behavior on top of that frozen
import boundary without renaming it. Naming is Pythonic
(``run_experience`` / ``run_experiences``) while preserving JavaScript
behavioral parity (``runExperience`` / ``runExperiences`` with a request-level
attribute merge).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

from convert_sdk.domain.context_state import ContextState
from convert_sdk.domain.results import ConversionResult, ExperienceResult, FeatureResult
from convert_sdk.evaluation.experiences import select_experience
from convert_sdk.evaluation.features import resolve_feature, resolve_features
from convert_sdk.tracking.conversions import create_conversion

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


class Context:
    """Per-visitor evaluation context for the Convert Python SDK.

    Per-visitor state (identity + stored visitor attributes + the link to the
    current immutable snapshot) lives in a typed
    :class:`~convert_sdk.domain.context_state.ContextState`, keeping visitor
    state separate from the shared snapshot. Location attributes remain a
    context-local overlay concern and are not part of that visitor-state model.

    Args:
        visitor_id: The stable visitor identity used for deterministic bucketing.
        snapshot: The immutable config snapshot to evaluate against.
        visitor_attributes: Optional stored visitor attributes (e.g. audience
            traits). Copied defensively so later caller mutations never affect
            the context.
        location_attributes: Optional stored location attributes (e.g. URL /
            site-area context) used for location-rule qualification.
    """

    def __init__(
        self,
        visitor_id: str,
        snapshot: "ConfigSnapshot",
        *,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> None:
        # Visitor identity + stored attributes + snapshot linkage live in the
        # typed ContextState (visitor state stays separate from the snapshot).
        self._state = ContextState(
            visitor_id=visitor_id,
            snapshot=snapshot,
            visitor_attributes=visitor_attributes,
        )
        self._snapshot = snapshot
        # Location is a context-local overlay, not part of ContextState.
        self._location_attributes: Mapping[str, Any] = MappingProxyType(
            dict(location_attributes or {})
        )

    @property
    def visitor_id(self) -> str:
        """The visitor identity bound to this context."""
        return self._state.visitor_id

    @property
    def visitor_attributes(self) -> Mapping[str, Any]:
        """A read-only view of the stored visitor attributes (Pythonic name)."""
        return self._state.visitor_attributes

    @property
    def attributes(self) -> Mapping[str, Any]:
        """A read-only view of the stored visitor attributes.

        Retained alias for :attr:`visitor_attributes`; both expose the same
        read-only stored visitor state.
        """
        return self._state.visitor_attributes

    # --- evaluation surface ------------------------------------------------

    def _merge(
        self,
        stored: Mapping[str, Any],
        overlay: Optional[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Overlay request-time attributes onto stored ones without mutation.

        Returns a fresh mapping; neither ``stored`` nor ``overlay`` is modified.
        """
        if not overlay:
            return stored
        merged = dict(stored)
        merged.update(overlay)
        return merged

    def run_experience(
        self,
        experience_key: str,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ExperienceResult]:
        """Evaluate a single experience by key for this visitor.

        Request-time ``attributes`` / ``location_attributes`` overlay the stored
        context state for this call only. Returns a typed
        :class:`~convert_sdk.domain.results.ExperienceResult` when the visitor
        qualifies and buckets into a variation, or ``None`` for any normal miss
        (missing experience, unqualified visitor, no active variation). Never
        raises for normal evaluation outcomes and performs no network I/O.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return select_experience(
            experience_key,
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )

    def run_experiences(
        self,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> List[ExperienceResult]:
        """Evaluate all applicable experiences for this visitor.

        Returns the list of typed results for the experiences the visitor
        qualifies for and buckets into; experiences that do not resolve are
        omitted (no ``None`` entries). Evaluation stays local to the snapshot —
        no network I/O.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        results: List[ExperienceResult] = []
        for experience in self._snapshot.experiences:
            key = experience.get("key")
            if key is None:
                continue
            result = select_experience(
                str(key),
                self._snapshot,
                visitor_id=self._state.visitor_id,
                visitor_attributes=visitor_attributes,
                location_attributes=location,
            )
            if result is not None:
                results.append(result)
        return results

    # --- feature resolution ------------------------------------------------

    def run_feature(
        self,
        feature_key: str,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Optional[FeatureResult]:
        """Resolve a single feature by key for this visitor.

        Resolves the feature locally from the visitor's selected variation —
        reading the variation's ``fullStackFeature`` change and casting the
        feature's variables by their declared types. Request-time ``attributes``
        / ``location_attributes`` overlay the stored context state for this call
        only. Returns a typed
        :class:`~convert_sdk.domain.results.FeatureResult` when the feature is
        declared and the visitor buckets into a variation carrying its change,
        or ``None`` for any normal miss (undeclared/unavailable/disabled feature,
        unqualified visitor). Never raises for normal evaluation outcomes and
        performs no network I/O.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return resolve_feature(
            feature_key,
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )

    def run_features(
        self,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> List[FeatureResult]:
        """Resolve all applicable features for this visitor.

        Returns one typed result per declared feature the visitor resolves to an
        enabled state; features the visitor does not bucket into are omitted (no
        ``None`` entries). Evaluation stays local to the snapshot — no network
        I/O.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return resolve_features(
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )

    # --- conversion tracking -----------------------------------------------

    def track_conversion(self, goal_key: str) -> ConversionResult:
        """Track a goal conversion for this visitor (Story 2.1).

        Resolves ``goal_key`` against the current immutable snapshot and creates
        an in-process conversion event associated with this visitor and the
        resolved goal identity. Returns a typed
        :class:`~convert_sdk.domain.results.ConversionResult`:

        * ``status == ConversionStatus.QUEUED`` — the goal resolved and an event
          was created (``result.event`` carries the
          :class:`~convert_sdk.domain.results.ConversionEvent`).
        * ``status == ConversionStatus.GOAL_NOT_FOUND`` — the goal key is absent
          from the loaded config. This is a diagnosable NON-EXCEPTION outcome
          (FR50), distinguishable from success via ``status`` alone — callers
          never need ``try``/``except`` to tell the two apart.

        Performs no network I/O and no payload serialization; event delivery,
        payload shaping, batching, deduplication, and flush land in later Epic 2
        stories. The Story 2.1 surface is goal-key only; richer conversion
        attributes (e.g. revenue) arrive in Story 2.2 as additional keyword
        arguments, keeping this signature forward-compatible.
        """
        return create_conversion(
            self._snapshot,
            visitor_id=self._state.visitor_id,
            goal_key=goal_key,
        )
