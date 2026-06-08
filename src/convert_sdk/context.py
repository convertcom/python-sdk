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

import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, TypeVar

from convert_sdk._internal.redaction import SafeContext, fingerprint_visitor
from convert_sdk.domain.context_state import ContextState
from convert_sdk.domain.results import (
    ConversionResult,
    CustomSegmentsResult,
    DiagnosticReason,
    EntityDiagnostic,
    ExperienceDiagnostic,
    ExperienceResult,
    FeatureDiagnostic,
    FeatureResult,
    GoalDiagnostic,
    _Diagnostic,
)
from convert_sdk.evaluation import entity_lookup
from convert_sdk.evaluation.bucketing import get_bucket_value_for_visitor
from convert_sdk.evaluation.experiences import select_experience
from convert_sdk.evaluation.features import resolve_feature, resolve_features
from convert_sdk.evaluation.segments import select_custom_segments
from convert_sdk.events import LifecycleEvent
from convert_sdk.logging import log_safe
from convert_sdk.ports.storage import visitor_state_key
from convert_sdk.tracking.conversions import create_conversion

# The distinct key under which matched custom-segment IDs are recorded inside
# the default-segment state (JS ``SegmentsKeys.CUSTOM_SEGMENTS`` parity). Kept in
# sync with the ``customSegments`` allowlist key in ``tracking/payloads.py``.
_CUSTOM_SEGMENTS_KEY = "customSegments"

# Generic over the four frozen Story-4.2 typed diagnostic dataclasses so
# ``_diagnose`` returns the SAME type the caller passes as ``cls`` (mypy strict:
# no implicit ``Any`` leaking out of the central diagnostic builder). Bounded to
# the shared ``_Diagnostic`` base so the ``reason``/``message``/``details``
# construction keywords are type-visible to mypy.
_DiagnosticT = TypeVar("_DiagnosticT", bound=_Diagnostic)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot
    from convert_sdk.ports.storage import DataStore
    from convert_sdk.tracking.tracker import Tracker


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
        default_segments: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
        tracker: Optional["Tracker"] = None,
        data_store: Optional["DataStore"] = None,
        environment: Optional[str] = None,
    ) -> None:
        # Visitor identity + stored attributes + default segments + snapshot
        # linkage live in the typed ContextState (visitor state stays separate
        # from the snapshot; default segments are a DISTINCT field from raw
        # attributes — Story 3.3, Critical Warning #7).
        self._state = ContextState(
            visitor_id=visitor_id,
            snapshot=snapshot,
            visitor_attributes=visitor_attributes or {},
            default_segments=default_segments or {},
        )
        self._snapshot = snapshot
        # Story 2.3: shared tracking orchestrator (dedup + queue). When None,
        # track_conversion falls back to stateless create_conversion.
        self._tracker = tracker
        # Story 3.2: the single per-Core DataStore (protocol type only — never
        # the concrete adapter; NFR19). When None (a Context built directly
        # rather than via Core), persistent set_attributes is an in-memory-only
        # rebind and persistence is skipped.
        self._data_store = data_store
        # Location is a context-local overlay, not part of ContextState.
        self._location_attributes: Mapping[str, Any] = MappingProxyType(
            dict(location_attributes or {})
        )
        # Story 4.3: the SDK config environment (or None for a directly
        # constructed context). It is an allowlist-safe operational field
        # (NFR6) included in the cross-SDK-comparable diagnostic field set so
        # diagnostics captured in a mixed Python/JS deployment carry the same
        # environment qualifier. Optional + defaulting to None keeps the
        # constructor backward compatible (Critical Warning #1).
        self._environment = environment

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

    @property
    def default_segments(self) -> Mapping[str, Any]:
        """A read-only view of this visitor's associated default segments.

        Distinct from :attr:`visitor_attributes` (Story 3.3 / FR14): default
        segments are a separate visitor-state concern that feeds reporting and
        conversion attribution, not raw audience traits. Observable for
        reporting/tracking without exposing the internal ``ContextState``.
        """
        return self._state.default_segments

    # --- mutable visitor state (Story 3.2) ---------------------------------

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Persistently update this visitor's stored attributes (FR11).

        Merges ``attributes`` into the context's stored visitor attributes —
        new keys override touched keys, untouched keys persist — and REBINDS the
        context's :class:`~convert_sdk.domain.context_state.ContextState` to the
        merged immutable copy. The original frozen state is never mutated in
        place, and the shared immutable ``ConfigSnapshot`` is never touched.

        Subsequent evaluations on this same context
        (:meth:`run_experience` / :meth:`run_experiences` / :meth:`run_feature`
        / :meth:`run_features`) use the updated state for
        audience/segment qualification. Deterministic bucketing inputs (visitor
        identity + config snapshot) are unaffected (FR25).

        This is the PERSISTENT update. It is distinct from the per-call
        request-time ``attributes`` overlay accepted by the evaluation methods:
        the overlay is ephemeral, takes precedence for that single call, and is
        NEVER written back here. Precedence for a call is request-time overlay >
        persisted/updated visitor state.

        The updated state is persisted through the injected ``DataStore`` (the
        same per-``Core`` persistence boundary and visitor-scoped key Story 3.1
        established) so a later ``create_context(visitor_id)`` for the same
        visitor rehydrates the update.

        Args:
            attributes: Visitor attributes to merge into the stored state.

        Returns:
            ``None``.
        """
        self._state = self._state.with_attributes(attributes)
        self._persist_visitor_state()

    def set_segments(self, segments: dict[str, Any]) -> None:
        """Persistently associate default visitor segments with this context (FR14).

        Shallow-merges ``segments`` into the context's DISTINCT default-segment
        state — new keys override touched keys, untouched keys persist — and
        REBINDS the context's
        :class:`~convert_sdk.domain.context_state.ContextState` to the merged
        immutable copy (the same frozen-dataclass rebind + persist-through-store
        pattern Story 3.2 used for :meth:`set_attributes`). The original frozen
        state is never mutated in place, the shared immutable ``ConfigSnapshot``
        is never touched, and the segments are kept STRICTLY SEPARATE from
        :attr:`visitor_attributes` (Critical Warning #7).

        Default segments feed reporting/conversion state — a subsequently tracked
        conversion's ``segments`` payload reflects the visitor's active default
        segments at conversion time — and a later
        ``create_context(visitor_id)`` for the same visitor rehydrates them
        through the injected ``DataStore`` (the same per-``Core`` persistence
        boundary and visitor-scoped key Story 3.1 established). Deterministic
        bucketing inputs (visitor identity + config snapshot) are unaffected
        (FR25). This is the Python analogue of the JS
        ``Context.setDefaultSegments`` → ``SegmentsManager.putSegments`` write
        path.

        Args:
            segments: Default visitor segments to merge into the stored state.

        Returns:
            ``None``.
        """
        self._state = self._state.with_segments(segments)
        self._persist_visitor_state()

    def run_custom_segments(
        self,
        segment_keys: list[str],
        rule_data: Optional[Mapping[str, Any]] = None,
    ) -> CustomSegmentsResult:
        """Evaluate custom segment matches for this visitor (FR15).

        Resolves the named segments from the immutable
        :class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot` and matches
        each segment's rule against the visitor's segment-rule input through the
        SAME pure-Python rule engine
        (:func:`convert_sdk.evaluation.rules.is_rule_matched`) the SDK uses for
        audience qualification — delegating to
        :func:`convert_sdk.evaluation.segments.select_custom_segments`.
        Evaluation is fully LOCAL and deterministic: it reads only the loaded
        snapshot plus visitor-scoped state and performs NO network I/O (Critical
        Warning #5).

        The per-call ``rule_data`` is an EPHEMERAL request-time overlay on the
        visitor's stored attributes (request value > persisted state precedence,
        reusing the Story 3.2 :meth:`ContextState.with_overlay` seam). It is
        NEVER written back into :attr:`visitor_attributes` (AC #5); only the
        resulting matched segment IDs are recorded — under a ``customSegments``
        list inside the DISTINCT default-segment state (JS ``VisitorSegments``
        parity) — and persisted through the injected ``DataStore`` so a later
        ``create_context(visitor_id)`` rehydrates them. Already-recorded segment
        IDs are not re-added (duplicates skipped).

        Args:
            segment_keys: The segment keys to evaluate.
            rule_data: Optional per-call segment-rule input. Overlays the stored
                visitor attributes for THIS call only.

        Returns:
            A typed :class:`~convert_sdk.domain.results.CustomSegmentsResult`
            carrying the newly matched segment IDs. A normal no-match returns a
            result with an empty ``matched_segment_ids`` — a typed, non-exception
            outcome (never a raw dict, never raises on a normal miss).
        """
        # Ephemeral request-time overlay (request > persisted), reusing the
        # Story 3.2 seam — never written back into visitor_attributes.
        segment_rule = self._state.with_overlay(rule_data)

        existing = self._state.default_segments.get(_CUSTOM_SEGMENTS_KEY) or []
        matched = select_custom_segments(
            self._snapshot,
            segment_keys,
            segment_rule,
            existing_ids=existing,
        )
        if matched:
            updated = list(existing) + matched
            self._state = self._state.with_segments({_CUSTOM_SEGMENTS_KEY: updated})
            self._persist_visitor_state()
        return CustomSegmentsResult(matched_segment_ids=tuple(matched))

    def _persist_visitor_state(self) -> None:
        """Persist the current visitor state through the injected ``DataStore``.

        No-op when no store is injected (a ``Context`` constructed directly
        rather than via ``Core``). The write is visitor-scoped: it targets only
        this visitor's state key (:func:`visitor_state_key`), never another
        visitor's and never a ``Core``-global key.

        The persisted value is a structured envelope
        ``{"attributes": {...}, "segments": {...}}`` so a later
        ``create_context(visitor_id)`` round-trips BOTH the visitor attributes
        (Story 3.2) and the default segments (Story 3.3) through the same store
        and hydrate route. The ``DataStore`` four-method surface is unchanged —
        a plain ``set`` of serialized state; no business logic lives in the
        store.
        """
        if self._data_store is None:
            return None
        key = visitor_state_key(self._state.visitor_id)
        self._data_store.set(
            key,
            {
                "attributes": dict(self._state.visitor_attributes),
                "segments": dict(self._state.default_segments),
            },
        )
        return None

    # --- diagnostic logging (Story 4.1) ------------------------------------

    def _log_bucketing(self, result: Optional["ExperienceResult"]) -> None:
        """Emit an additive, allowlist-only evaluation-decision log record.

        Carries ONLY allowlisted fields (NFR6): the entity key, the bucketed
        variation key, and a HASHED visitor reference (never the raw
        ``visitor_id``, never raw visitor attributes). Purely observational — it
        runs after the evaluation has already produced ``result`` and cannot
        change the outcome (Critical Warning #6).
        """
        if result is None:
            return
        log_safe(
            LifecycleEvent.BUCKETING,
            level=logging.DEBUG,
            context=SafeContext(entity_key=result.experience_key),
            visitor=fingerprint_visitor(self._state.visitor_id),
            variation_key=result.variation_key,
        )

    def _log_conversion(self, result: "ConversionResult") -> None:
        """Emit an additive, allowlist-only conversion-tracking log record.

        Carries ONLY the goal key, the typed outcome, and a hashed visitor
        reference — never the raw ``conversion_data`` values, revenue payload,
        raw ``visitor_id``, or visitor attributes (NFR6, Task 4.3). Observational
        only; runs after the tracking result is produced.
        """
        log_safe(
            LifecycleEvent.CONVERSION,
            level=logging.DEBUG,
            context=SafeContext(entity_key=result.goal_key),
            visitor=fingerprint_visitor(self._state.visitor_id),
            outcome=result.status.value,
        )

    def _log_diagnostic(
        self,
        entity_key: Optional[str],
        reason: DiagnosticReason,
        *,
        environment: Optional[str] = None,
        bucket_value: Optional[int] = None,
        variation_key: Optional[str] = None,
    ) -> None:
        """Emit an additive, allowlist-only diagnostic-outcome log record (FR52).

        Routes through the SAME Story 4.1 :func:`log_safe` seam every other SDK
        log call site uses (no separate diagnostics module) so support teams see
        the identical closed ``reason`` code in logs and in the returned typed
        diagnostic. Story 4.3 mirrors the partial cross-SDK-comparable field set
        (``reason``, ``environment``, ``bucket_value``, ``variation_key``, and a
        HASHED visitor reference) into the log record so a mixed Python/JS
        deployment can correlate diagnostic output for the same scenario. It
        carries ONLY allowlist-safe fields — never the raw ``visitor_id``,
        visitor attributes, or any PII (NFR6/NFR51, Critical Warning #3).
        Observational only — it runs after the diagnostic outcome is already
        determined and cannot change it.
        """
        # Only emit allowlist-safe fields that are present (omit None) so the
        # record stays compact and the partial field set is honest about misses.
        optional: Dict[str, Any] = {}
        if environment is not None:
            optional["environment"] = environment
        if bucket_value is not None:
            optional["bucket_value"] = bucket_value
        if variation_key is not None:
            optional["variation_key"] = variation_key
        log_safe(
            LifecycleEvent.DIAGNOSTIC,
            level=logging.DEBUG,
            context=SafeContext(entity_key=entity_key),
            visitor=fingerprint_visitor(self._state.visitor_id),
            reason=reason.value,
            **optional,
        )

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
        result = select_experience(
            experience_key,
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )
        self._log_bucketing(result)
        return result

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
                self._log_bucketing(result)
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

    def track_conversion(
        self,
        goal_key: str,
        *,
        revenue: Optional[float] = None,
        conversion_data: Optional[Mapping[str, Any]] = None,
        force_multiple: bool = False,
    ) -> ConversionResult:
        """Track a goal conversion for this visitor (Stories 2.1 + 2.2 + 2.3).

        Resolves ``goal_key`` against the current immutable snapshot and creates
        an in-process conversion event associated with this visitor and the
        resolved goal identity, carrying the visitor's attribution context
        (active segments + active variation/bucketing assignments) (AC#1, FR33,
        FR34). Story 2.3 activates the canonical PRD ``force_multiple`` keyword
        and routes the call through the shared tracker (dedup + batch queue) when
        one is configured (i.e. when the context was created via ``Core``).

        Deduplication is keyed by ``(visitor_id, goal_id)`` and is by goal
        identity, not payload content — a differing ``revenue`` /
        ``conversion_data`` does NOT defeat dedup. ``force_multiple=True``
        overrides dedup to re-track an already-tracked goal (re-sending the
        transaction/``goalData`` path, JS parity).

        Returns a typed
        :class:`~convert_sdk.domain.results.ConversionResult`:

        * ``status == QUEUED`` (``tracked=True``, ``reason=None``) — the goal
          resolved and an event was enqueued.
        * ``status == DEDUPLICATED`` (``tracked=False``,
          ``reason="deduplicated"``) — a default-mode duplicate for an
          already-tracked ``(visitor_id, goal_id)``; no second event enqueued.
        * ``status == GOAL_NOT_FOUND`` (``tracked=False``,
          ``reason="goal_not_found"``) — the goal key is absent from the loaded
          config. A diagnosable NON-EXCEPTION outcome (FR50).

        When the context has no shared tracker (constructed directly rather than
        via ``Core``), tracking falls back to the stateless Story 2.1/2.2
        ``create_conversion`` — no dedup, no queue (``force_multiple`` has no
        effect in that fallback path).

        Raises:
            ConversionDataError: if a ``conversion_data`` value is not a JSON
                primitive. Programmer misuse fails fast and is never silently
                downgraded to a no-result (AC#3).

        The enqueue path performs no network I/O and stays lightweight (NFR5);
        delivery happens at flush time (``Core.flush()``).
        """
        if self._tracker is not None:
            result = self._tracker.track(
                visitor_id=self._state.visitor_id,
                goal_key=goal_key,
                revenue=revenue,
                conversion_data=conversion_data,
                visitor_attributes=self._state.visitor_attributes,
                default_segments=self._state.default_segments,
                force_multiple=force_multiple,
            )
        else:
            # Fallback: stateless create_conversion (no dedup/queue) for a
            # Context constructed without a shared tracker.
            result = create_conversion(
                self._snapshot,
                visitor_id=self._state.visitor_id,
                goal_key=goal_key,
                revenue=revenue,
                conversion_data=conversion_data,
                visitor_attributes=self._state.visitor_attributes,
                default_segments=self._state.default_segments,
            )
        self._log_conversion(result)
        return result

    # --- entity lookup (Story 3.4 / FR28) ----------------------------------

    def get_config_entity(
        self, entity_type: str, key: str
    ) -> Optional[Mapping[str, Any]]:
        """Look up a configuration entity by key for advanced/debugging use (FR28).

        Resolves the typed config entity of ``entity_type`` whose ``key`` matches,
        from the immutable :class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`
        this context already holds, via the snapshot's precomputed by-key index
        (delegating to :func:`convert_sdk.evaluation.entity_lookup.resolve_entity`).
        This is a READ-ONLY advanced-integration/debugging helper: it performs NO
        network I/O and never mutates the snapshot.

        Args:
            entity_type: A supported entity-type identifier — one of
                ``"experiences"``, ``"features"``, ``"goals"``, ``"audiences"``,
                ``"segments"`` (see
                :data:`convert_sdk.evaluation.entity_lookup.SUPPORTED_ENTITY_TYPES`).
            key: The entity ``key`` to resolve.

        Returns:
            The matching typed domain entity, or ``None`` on a normal miss
            (unknown key, a known key under the wrong ``entity_type``, or an
            unknown/unsupported ``entity_type``). Never raises on a normal miss
            and never returns a sentinel string.

        Note:
            Story 4.2 will enrich the ``None`` miss into the FR50 typed-reason
            result object (naming *why* the lookup did not resolve) WITHOUT
            changing this hit return shape.
        """
        return entity_lookup.resolve_entity(self._snapshot, entity_type, key)

    def get_config_entities(
        self, entity_type: str, keys: list[str]
    ) -> list[Mapping[str, Any]]:
        """Look up multiple configuration entities by key (FR28).

        Resolves each key in ``keys`` of ``entity_type`` over the snapshot's
        by-key index (delegating to
        :func:`convert_sdk.evaluation.entity_lookup.resolve_entities`) and returns
        the matched entities in the supplied order, SKIPPING keys that do not
        resolve (no ``None`` placeholders). Read-only; no network I/O.

        Args:
            entity_type: A supported entity-type identifier (see
                :meth:`get_config_entity`).
            keys: The entity keys to resolve.

        Returns:
            The list of matched typed domain entities; an empty list when none
            resolve (including an unknown/unsupported ``entity_type``). Never
            raises on a normal miss.
        """
        return entity_lookup.resolve_entities(self._snapshot, entity_type, keys)

    def get_config_entity_by_id(
        self, entity_type: str, entity_id: str
    ) -> Optional[Mapping[str, Any]]:
        """Look up a configuration entity by id for advanced/debugging use (FR28).

        Resolves the typed config entity of ``entity_type`` whose ``id`` matches,
        over the snapshot's precomputed by-id index (delegating to
        :func:`convert_sdk.evaluation.entity_lookup.resolve_entity_by_id`).
        Read-only; no network I/O; never mutates the snapshot.

        Args:
            entity_type: A supported entity-type identifier (see
                :meth:`get_config_entity`).
            entity_id: The entity ``id`` to resolve.

        Returns:
            The matching typed domain entity, or ``None`` on a normal miss
            (unknown id, wrong/unsupported ``entity_type``). Never raises on a
            normal miss. (Story 4.2 enriches the ``None`` miss per
            :meth:`get_config_entity`.)
        """
        return entity_lookup.resolve_entity_by_id(self._snapshot, entity_type, entity_id)

    # --- diagnosable no-result outcomes (Story 4.2 / FR50) -----------------
    #
    # The ADDITIVE, opt-in typed-diagnostic surface. It names *why* a request
    # did or did not resolve using the closed
    # :class:`~convert_sdk.domain.results.DiagnosticReason` vocabulary, WITHOUT
    # changing any existing return contract: ``run_experience`` / ``run_feature``
    # / ``get_config_entity*`` keep their ``None``/``Optional`` shapes
    # (Critical Warning #1). Each ``diagnose_*`` is a thin read-only wrapper over
    # the same local evaluation/lookup helpers — it performs NO network I/O, does
    # not mutate state, and leaves determinism untouched. A miss-path diagnostic
    # is mirrored to the Story 4.1 log seam with the same reason code.

    def diagnose_experience(
        self,
        experience_key: str,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> ExperienceDiagnostic:
        """Diagnose why an experience did or did not resolve for this visitor (FR50).

        Returns a typed
        :class:`~convert_sdk.domain.results.ExperienceDiagnostic` naming the
        closed reason — ``EXPERIENCE_NOT_FOUND`` (no experience matches the key),
        ``AUDIENCE_MISMATCH`` (the visitor does not qualify for the experience's
        audience/location rules), or ``RESOLVED`` (the visitor qualifies and
        buckets into a variation). Additive to :meth:`run_experience`, whose
        ``Optional[ExperienceResult]`` return shape is unchanged.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        experience = self._snapshot.get_experience_by_key(experience_key)
        if experience is None:
            return self._diagnose(
                ExperienceDiagnostic,
                experience_key,
                DiagnosticReason.EXPERIENCE_NOT_FOUND,
                "no experience matches the requested key",
                {"experience_key": experience_key},
            )
        result = select_experience(
            experience_key,
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )
        if result is not None:
            # Story 4.3: recompute the deterministic bucket value for the
            # resolved experience so the diagnostic carries the cross-SDK
            # comparable bucketing outcome. This mirrors the value
            # ``select_experience`` used internally (same visitor + experience
            # id → same value against the same snapshot) without changing the
            # frozen ``ExperienceResult`` public shape.
            bucket_value = get_bucket_value_for_visitor(
                self._state.visitor_id, experience_id=result.experience_id
            )
            return self._diagnose(
                ExperienceDiagnostic,
                experience_key,
                DiagnosticReason.RESOLVED,
                "experience resolved to a variation",
                {"experience_key": experience_key, "variation_key": result.variation_key},
                bucket_value=bucket_value,
                variation_key=result.variation_key,
            )
        # The experience exists but produced no result: the visitor did not
        # qualify for (or bucket within) it — surfaced as an audience mismatch.
        return self._diagnose(
            ExperienceDiagnostic,
            experience_key,
            DiagnosticReason.AUDIENCE_MISMATCH,
            "the visitor did not qualify for this experience",
            {"experience_key": experience_key},
        )

    def diagnose_feature(
        self,
        feature_key: str,
        *,
        attributes: Optional[Mapping[str, Any]] = None,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> FeatureDiagnostic:
        """Diagnose why a feature did or did not resolve for this visitor (FR50).

        Returns a typed :class:`~convert_sdk.domain.results.FeatureDiagnostic`
        naming the closed reason — ``FEATURE_NOT_FOUND`` (no feature matches the
        key), ``FEATURE_NOT_IN_SELECTED_VARIATIONS`` (the feature is declared but
        the visitor's selected variation(s) carry no change for it), or
        ``RESOLVED``. Additive to :meth:`run_feature`.
        """
        visitor_attributes = self._state.with_overlay(attributes)
        location = self._merge(self._location_attributes, location_attributes)
        feature = self._snapshot.get_feature_by_key(feature_key)
        if feature is None:
            return self._diagnose(
                FeatureDiagnostic,
                feature_key,
                DiagnosticReason.FEATURE_NOT_FOUND,
                "no feature matches the requested key",
                {"feature_key": feature_key},
            )
        result = resolve_feature(
            feature_key,
            self._snapshot,
            visitor_id=self._state.visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location,
        )
        if result is not None:
            return self._diagnose(
                FeatureDiagnostic,
                feature_key,
                DiagnosticReason.RESOLVED,
                "feature resolved to an enabled state",
                {"feature_key": feature_key},
            )
        return self._diagnose(
            FeatureDiagnostic,
            feature_key,
            DiagnosticReason.FEATURE_NOT_IN_SELECTED_VARIATIONS,
            "the feature is declared but not carried by the visitor's selected variations",
            {"feature_key": feature_key},
        )

    def diagnose_goal(self, goal_key: str) -> GoalDiagnostic:
        """Diagnose whether a goal resolves against the loaded config (FR50).

        Returns a typed :class:`~convert_sdk.domain.results.GoalDiagnostic`
        naming ``GOAL_NOT_FOUND`` (no goal matches the key) or ``RESOLVED``. This
        is the typed counterpart to the
        :class:`~convert_sdk.domain.results.ConversionStatus.GOAL_NOT_FOUND`
        tracking outcome — :meth:`track_conversion`'s return shape is unchanged.
        """
        goal = self._snapshot.get_goal_by_key(goal_key)
        if goal is None:
            return self._diagnose(
                GoalDiagnostic,
                goal_key,
                DiagnosticReason.GOAL_NOT_FOUND,
                "no goal matches the requested key",
                {"goal_key": goal_key},
            )
        return self._diagnose(
            GoalDiagnostic,
            goal_key,
            DiagnosticReason.RESOLVED,
            "goal resolved",
            {"goal_key": goal_key},
        )

    def diagnose_entity(self, entity_type: str, key: str) -> EntityDiagnostic:
        """Diagnose why a config-entity lookup did or did not resolve (FR50).

        The additive, typed counterpart to :meth:`get_config_entity` (whose
        ``None``-return contract is unchanged — Critical Warning #1). Returns a
        typed :class:`~convert_sdk.domain.results.EntityDiagnostic` naming
        ``PROJECT_MAPPING_REQUIRED`` (the loaded config has no project mapping, so
        no entity can be resolved), ``ENTITY_NOT_FOUND`` (unknown key, wrong or
        unsupported ``entity_type``), or ``RESOLVED``.
        """
        details = {"entity_type": entity_type, "entity_key": key}
        if self._snapshot.project_id is None:
            return self._diagnose(
                EntityDiagnostic,
                key,
                DiagnosticReason.PROJECT_MAPPING_REQUIRED,
                "the loaded config has no project mapping",
                details,
            )
        entity = entity_lookup.resolve_entity(self._snapshot, entity_type, key)
        if entity is None:
            return self._diagnose(
                EntityDiagnostic,
                key,
                DiagnosticReason.ENTITY_NOT_FOUND,
                "no entity matches the requested key for this entity_type",
                details,
            )
        return self._diagnose(
            EntityDiagnostic,
            key,
            DiagnosticReason.RESOLVED,
            "entity resolved",
            details,
        )

    def _diagnose(
        self,
        cls: type[_DiagnosticT],
        entity_key: Optional[str],
        reason: DiagnosticReason,
        message: str,
        details: Mapping[str, Any],
        *,
        bucket_value: Optional[int] = None,
        variation_key: Optional[str] = None,
    ) -> _DiagnosticT:
        """Build a typed diagnostic and mirror miss-path reasons to the log seam.

        Centralizes the log emission so every ``diagnose_*`` path emits the SAME
        allowlist-only, hashed-visitor diagnostic record through Story 4.1's
        :func:`log_safe`. A ``RESOLVED`` outcome is not a miss, so it is not
        logged (parity with the observational bucketing/conversion logs).

        Story 4.3: the typed diagnostic's read-only ``details`` mapping (Story
        4.2's frozen surface — NOT new top-level fields) is augmented with the
        partial cross-SDK-comparable field set so a mixed Python/JS deployment
        can compare diagnostic output for the same visitor scenario:

        * ``reason`` — the closed :class:`DiagnosticReason` code value.
        * ``environment`` — the SDK config environment (``None`` when unwired).
        * ``visitor_ref`` — the HASHED visitor reference via
          :func:`~convert_sdk._internal.redaction.fingerprint_visitor`; the raw
          ``visitor_id`` NEVER appears (NFR6/NFR51, Critical Warning #1).
        * ``bucket_value`` / ``variation_key`` — present only on a resolved
          experience diagnostic (the only path that buckets); ``None`` otherwise.

        The AC-1 fields ``config_version``, ``bucketing_inputs`` (key/traffic/
        seed/salt), and ``experience_key`` completion are intentionally DEFERRED
        to Story 4.5 and are NOT emitted here. The formal byte-comparable
        contract document is owned by Story 4.5; the parity-comparison helper +
        diagnostic-vector fixtures are owned by Story 5.1.
        """
        # Merge the comparable field set onto the caller's allowlist-safe
        # details WITHOUT mutating the caller's mapping. The _Diagnostic
        # dataclass re-wraps this read-only in __post_init__.
        comparable: Dict[str, Any] = dict(details)
        comparable["reason"] = reason.value
        comparable["environment"] = self._environment
        comparable["visitor_ref"] = fingerprint_visitor(self._state.visitor_id)
        comparable["bucket_value"] = bucket_value
        comparable["variation_key"] = variation_key
        diagnostic = cls(reason=reason, message=message, details=comparable)
        if reason is not DiagnosticReason.RESOLVED:
            self._log_diagnostic(
                entity_key,
                reason,
                environment=self._environment,
                bucket_value=bucket_value,
                variation_key=variation_key,
            )
        return diagnostic
