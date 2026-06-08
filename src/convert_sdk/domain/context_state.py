"""Typed per-visitor context state (Story 1.3).

:class:`ContextState` is the typed, immutable foundation for a visitor context.
It keeps visitor-specific state — the visitor identity and stored visitor
attributes — strictly separate from the shared, immutable
:class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`:

* The snapshot is held *by reference*, shared across every context created from
  the same initialized ``Core`` — it is never copied or mutated per visitor.
* Visitor attributes are copied defensively at construction and exposed only as
  a read-only mapping, so caller-side mutation can never leak into the stored
  state.
* Request-time attribute overlays are produced via :meth:`with_overlay`, which
  returns a fresh mapping and never mutates the stored baseline (FR12/FR13).

This module is internal domain plumbing; nothing here is part of the public
``convert_sdk`` import boundary (the public surface stays ``Core`` / ``Context``
plus the typed result models). It exists so later persistence/segment stories
(3.2, 3.3) have a stable, snapshot-independent place to grow visitor state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


@dataclass(frozen=True)
class ContextState:
    """Immutable per-visitor state bound to the current config snapshot.

    Args:
        visitor_id: The stable visitor identity used for deterministic bucketing.
        snapshot: The current immutable :class:`ConfigSnapshot`, shared by
            reference (never copied or mutated per visitor).
        visitor_attributes: Optional stored visitor attributes (e.g. audience
            traits). Copied defensively and wrapped read-only so later caller
            mutations never affect this state.
    """

    visitor_id: str
    snapshot: "ConfigSnapshot"
    visitor_attributes: Mapping[str, Any] = field(default_factory=dict)
    default_segments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Store a defensive, read-only copy so caller-side mutation cannot leak
        # into the stored visitor state (frozen dataclass requires __setattr__).
        if not isinstance(self.visitor_attributes, MappingProxyType):
            object.__setattr__(
                self,
                "visitor_attributes",
                MappingProxyType(dict(self.visitor_attributes or {})),
            )
        # Story 3.3: default segments are a DISTINCT visitor-state concern, kept
        # strictly separate from visitor_attributes (Critical Warning #7). They
        # are copied defensively and wrapped read-only, exactly like attributes.
        if not isinstance(self.default_segments, MappingProxyType):
            object.__setattr__(
                self,
                "default_segments",
                MappingProxyType(dict(self.default_segments or {})),
            )

    def with_overlay(self, overlay: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Return stored visitor attributes overlaid with request-time values.

        Per-call ``overlay`` keys override stored keys for that call only.
        Returns a fresh mapping; the stored baseline (and ``overlay``) are never
        mutated. When ``overlay`` is empty/``None`` the read-only baseline view
        is returned unchanged.

        This is the EPHEMERAL request-time seam (Story 1.3 / FR12). It is kept
        deliberately distinct from :meth:`with_attributes`, which produces a
        PERSISTENT update to the stored baseline (Story 3.2).
        """
        if not overlay:
            return self.visitor_attributes
        merged = dict(self.visitor_attributes)
        merged.update(overlay)
        return merged

    def with_attributes(self, new_attributes: Optional[Mapping[str, Any]]) -> "ContextState":
        """Return a NEW :class:`ContextState` with ``new_attributes`` merged in.

        This is the immutable, PERSISTENT visitor-attribute update operation
        (Story 3.2 / FR11). It performs a key-merge of the stored visitor
        attributes with ``new_attributes`` — new keys override touched keys,
        untouched keys persist — mirroring the JS
        ``objectDeepMerge(this._visitorProperties, attributes)`` behavior in
        ``Context.getVisitorProperties``.

        The original instance is never mutated: a fresh frozen ``ContextState``
        is returned, carrying the same ``visitor_id`` and the same
        :class:`ConfigSnapshot` by reference (the snapshot is shared, never
        copied or mutated per visitor — Critical Warnings #1/#2). When
        ``new_attributes`` is empty/``None`` the merge is a content-equal no-op
        copy, preserving determinism (AC #4).

        Distinct from :meth:`with_overlay`: this update is meant to be persisted
        (the caller writes it through the ``DataStore``), whereas ``with_overlay``
        is a per-call ephemeral merge that is never written back.
        """
        merged = dict(self.visitor_attributes)
        if new_attributes:
            merged.update(new_attributes)
        return ContextState(
            visitor_id=self.visitor_id,
            snapshot=self.snapshot,
            visitor_attributes=merged,
            default_segments=self.default_segments,
        )

    def with_segments(self, new_segments: Optional[Mapping[str, Any]]) -> "ContextState":
        """Return a NEW :class:`ContextState` with ``new_segments`` merged in.

        This is the immutable, PERSISTENT default-segment association operation
        (Story 3.3 / FR14). It shallow-merges the stored default segments with
        ``new_segments`` — new keys override touched keys, untouched keys persist
        — mirroring the JS ``SegmentsManager.putSegments`` shallow-merge of the
        stored ``segments`` with the new segment values.

        The update targets ONLY the DISTINCT :attr:`default_segments` field;
        ``visitor_attributes`` are carried through unchanged so segment state and
        raw attribute state stay strictly separate (Critical Warning #7). The
        original instance is never mutated: a fresh frozen ``ContextState`` is
        returned, carrying the same ``visitor_id`` and the same
        :class:`ConfigSnapshot` by reference (the snapshot is shared, never
        copied or mutated per visitor — Critical Warning #10). When
        ``new_segments`` is empty/``None`` the merge is a content-equal no-op
        copy, preserving determinism (AC #4 / FR25).

        This mirrors :meth:`with_attributes` for the segment field and is the
        single shared segment-merge seam — callers persist the returned state
        through the ``DataStore`` exactly as they do for attribute updates.
        """
        merged = dict(self.default_segments)
        if new_segments:
            merged.update(new_segments)
        return ContextState(
            visitor_id=self.visitor_id,
            snapshot=self.snapshot,
            visitor_attributes=self.visitor_attributes,
            default_segments=merged,
        )
