"""Immutable config snapshot for the Convert Python SDK (Story 1.2).

A :class:`ConfigSnapshot` is the current, immutable view of loaded config. The
SDK *replaces* the current snapshot atomically rather than mutating nested
dictionaries in place (architecture guardrail FR26/FR27). Minimal entity key
indexes are precomputed at construction so later stories can look up
experiences/features/goals/etc. in O(1) without mutating the snapshot.

Story scope (1.2): this layer only stores and indexes config. It does NOT
implement evaluation, bucketing, or variation selection — those land in later
stories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence


def _index_by(entities: Sequence[Mapping[str, Any]], attr: str) -> Dict[str, Any]:
    """Build a read-only key→entity index over the given attribute."""
    index: Dict[str, Any] = {}
    for entity in entities:
        value = entity.get(attr)
        if value is not None:
            index[str(value)] = entity
    return index


@dataclass(frozen=True)
class ConfigSnapshot:
    """An immutable snapshot of a loaded Convert config.

    Constructed via :meth:`from_normalized` (or the ``config_loader``). Direct
    construction expects already-normalized, internally-owned data. All stored
    collections are wrapped so the snapshot cannot be mutated after creation.
    """

    account_id: str
    project_id: Optional[str]
    experiences: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    features: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    goals: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    audiences: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    segments: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    # Precomputed indexes (read-only mappings). Stored on the frozen instance
    # via object.__setattr__ in __post_init__ because they derive from the
    # collections above.
    _experiences_by_key: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _experiences_by_id: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _features_by_key: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _features_by_id: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _audiences_by_id: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _audiences_by_key: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_experiences_by_key", MappingProxyType(_index_by(self.experiences, "key"))
        )
        object.__setattr__(
            self, "_experiences_by_id", MappingProxyType(_index_by(self.experiences, "id"))
        )
        object.__setattr__(
            self, "_features_by_key", MappingProxyType(_index_by(self.features, "key"))
        )
        object.__setattr__(
            self, "_features_by_id", MappingProxyType(_index_by(self.features, "id"))
        )
        object.__setattr__(
            self, "_audiences_by_id", MappingProxyType(_index_by(self.audiences, "id"))
        )
        object.__setattr__(
            self, "_audiences_by_key", MappingProxyType(_index_by(self.audiences, "key"))
        )

    @classmethod
    def from_normalized(cls, normalized: Mapping[str, Any]) -> "ConfigSnapshot":
        """Build a snapshot from an already-normalized config mapping.

        The ``config_loader`` is responsible for validating and normalizing raw
        boundary payloads before calling this. Collections are stored as tuples
        so the snapshot owns immutable copies and never aliases caller data.
        """
        def _freeze(items: Sequence[Mapping[str, Any]]) -> tuple:
            return tuple(MappingProxyType(dict(item)) for item in items)

        return cls(
            account_id=str(normalized["account_id"]),
            project_id=(
                str(normalized["project"]["id"])
                if normalized.get("project") and normalized["project"].get("id") is not None
                else None
            ),
            experiences=_freeze(normalized.get("experiences", [])),
            features=_freeze(normalized.get("features", [])),
            goals=_freeze(normalized.get("goals", [])),
            audiences=_freeze(normalized.get("audiences", [])),
            segments=_freeze(normalized.get("segments", [])),
        )

    # --- Read-only accessors (no mutation) ---------------------------------

    def get_experience_by_key(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._experiences_by_key.get(key)

    def get_experience_by_id(self, experience_id: str) -> Optional[Mapping[str, Any]]:
        return self._experiences_by_id.get(experience_id)

    def get_feature_by_key(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._features_by_key.get(key)

    def get_feature_by_id(self, feature_id: str) -> Optional[Mapping[str, Any]]:
        return self._features_by_id.get(feature_id)

    def get_audience_by_id(self, audience_id: str) -> Optional[Mapping[str, Any]]:
        return self._audiences_by_id.get(audience_id)

    def get_audience_by_key(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._audiences_by_key.get(key)
