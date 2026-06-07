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

    def __post_init__(self) -> None:
        # Store a defensive, read-only copy so caller-side mutation cannot leak
        # into the stored visitor state (frozen dataclass requires __setattr__).
        if not isinstance(self.visitor_attributes, MappingProxyType):
            object.__setattr__(
                self,
                "visitor_attributes",
                MappingProxyType(dict(self.visitor_attributes or {})),
            )

    def with_overlay(self, overlay: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Return stored visitor attributes overlaid with request-time values.

        Per-call ``overlay`` keys override stored keys for that call only.
        Returns a fresh mapping; the stored baseline (and ``overlay``) are never
        mutated. When ``overlay`` is empty/``None`` the read-only baseline view
        is returned unchanged.
        """
        if not overlay:
            return self.visitor_attributes
        merged = dict(self.visitor_attributes)
        merged.update(overlay)
        return merged
