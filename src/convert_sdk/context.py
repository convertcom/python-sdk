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

from convert_sdk.domain.results import ExperienceResult, FeatureResult
from convert_sdk.evaluation.experiences import select_experience
from convert_sdk.evaluation.features import resolve_feature, resolve_features

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


class Context:
    """Per-visitor evaluation context for the Convert Python SDK.

    Args:
        visitor_id: The stable visitor identity used for deterministic bucketing.
        snapshot: The immutable config snapshot to evaluate against.
        attributes: Optional stored visitor attributes (e.g. audience traits).
            Copied defensively so later caller mutations never affect the
            context.
        location_attributes: Optional stored location attributes (e.g. URL /
            site-area context) used for location-rule qualification.
    """

    def __init__(
        self,
        visitor_id: str,
        snapshot: "ConfigSnapshot",
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._visitor_id = visitor_id
        self._snapshot = snapshot
        # Store immutable copies so caller-side mutation cannot leak in.
        self._attributes: Mapping[str, Any] = MappingProxyType(dict(attributes or {}))
        self._location_attributes: Mapping[str, Any] = MappingProxyType(
            dict(location_attributes or {})
        )

    @property
    def visitor_id(self) -> str:
        """The visitor identity bound to this context."""
        return self._visitor_id

    @property
    def attributes(self) -> Mapping[str, Any]:
        """A read-only view of the stored visitor attributes."""
        return self._attributes

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
        visitor_attributes = self._merge(self._attributes, attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return select_experience(
            experience_key,
            self._snapshot,
            visitor_id=self._visitor_id,
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
        visitor_attributes = self._merge(self._attributes, attributes)
        location = self._merge(self._location_attributes, location_attributes)
        results: List[ExperienceResult] = []
        for experience in self._snapshot.experiences:
            key = experience.get("key")
            if key is None:
                continue
            result = select_experience(
                str(key),
                self._snapshot,
                visitor_id=self._visitor_id,
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
        visitor_attributes = self._merge(self._attributes, attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return resolve_feature(
            feature_key,
            self._snapshot,
            visitor_id=self._visitor_id,
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
        visitor_attributes = self._merge(self._attributes, attributes)
        location = self._merge(self._location_attributes, location_attributes)
        return resolve_features(
            self._snapshot,
            visitor_id=self._visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )
