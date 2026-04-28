"""Visitor-scoped state foundation for reusable SDK contexts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

from .config_snapshot import freeze_mapping, freeze_value


EMPTY_VISITOR_ATTRIBUTES: Mapping[str, Any] = MappingProxyType({})
EMPTY_VISITOR_PROPERTIES: Mapping[str, Any] = MappingProxyType({})
EMPTY_DEFAULT_SEGMENTS: tuple[str, ...] = ()


def _freeze_visitor_attributes(
    visitor_attributes: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if visitor_attributes is None:
        return EMPTY_VISITOR_ATTRIBUTES
    if not isinstance(visitor_attributes, Mapping):
        raise TypeError("visitor_attributes must be a mapping")
    return freeze_mapping(visitor_attributes)


def _freeze_visitor_properties(
    visitor_properties: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if visitor_properties is None:
        return EMPTY_VISITOR_PROPERTIES
    if not isinstance(visitor_properties, Mapping):
        raise TypeError("visitor_properties must be a mapping")
    return freeze_mapping(visitor_properties)


def _freeze_default_segments(
    default_segments: Optional[Sequence[str]],
) -> tuple[str, ...]:
    if default_segments is None:
        return EMPTY_DEFAULT_SEGMENTS
    if isinstance(default_segments, (str, bytes, bytearray)):
        raise TypeError("default_segments must be a sequence of strings")
    if not isinstance(default_segments, Sequence):
        raise TypeError("default_segments must be a sequence of strings")

    normalized_segments: list[str] = []
    seen: set[str] = set()
    for segment in default_segments:
        segment_key = str(segment).strip()
        if not segment_key or segment_key in seen:
            continue
        normalized_segments.append(segment_key)
        seen.add(segment_key)
    return tuple(normalized_segments)


def _merge_persistent_mapping(
    stored_mapping: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    replace: bool = False,
) -> Mapping[str, Any]:
    if not isinstance(updates, Mapping):
        raise TypeError("updates must be a mapping")

    merged_mapping = {} if replace else dict(stored_mapping)
    for key, value in updates.items():
        merged_mapping[str(key)] = freeze_value(value)
    return MappingProxyType(merged_mapping)


def merge_visitor_attributes(
    stored_attributes: Mapping[str, Any],
    stored_properties: Mapping[str, Any],
    request_attributes: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    merged_attributes = dict(stored_attributes)
    merged_attributes.update(dict(stored_properties))

    if request_attributes is not None:
        if not isinstance(request_attributes, Mapping):
            raise TypeError("request_attributes must be a mapping")
        for key, value in request_attributes.items():
            merged_attributes[str(key)] = freeze_value(value)
    return MappingProxyType(merged_attributes)


@dataclass(frozen=True)
class ContextState:
    """Immutable visitor-scoped state for a reusable SDK context."""

    visitor_id: str
    visitor_attributes: Mapping[str, Any]
    visitor_properties: Mapping[str, Any]
    default_segments: tuple[str, ...]

    @classmethod
    def create(
        cls,
        visitor_id: str,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        visitor_properties: Optional[Mapping[str, Any]] = None,
        default_segments: Optional[Sequence[str]] = None,
    ) -> "ContextState":
        return cls(
            visitor_id=visitor_id,
            visitor_attributes=_freeze_visitor_attributes(visitor_attributes),
            visitor_properties=_freeze_visitor_properties(visitor_properties),
            default_segments=_freeze_default_segments(default_segments),
        )

    def resolve_visitor_attributes(
        self,
        request_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Merge stored visitor attributes with request-scoped overrides."""

        return merge_visitor_attributes(
            self.visitor_attributes,
            self.visitor_properties,
            request_attributes,
        )

    def update_visitor_attributes(
        self,
        visitor_attributes: Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> "ContextState":
        """Return a new state with updated stored visitor attributes."""

        return ContextState(
            visitor_id=self.visitor_id,
            visitor_attributes=_merge_persistent_mapping(
                self.visitor_attributes,
                visitor_attributes,
                replace=replace,
            ),
            visitor_properties=self.visitor_properties,
            default_segments=self.default_segments,
        )

    def update_visitor_properties(
        self,
        visitor_properties: Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> "ContextState":
        """Return a new state with updated stored visitor properties."""

        return ContextState(
            visitor_id=self.visitor_id,
            visitor_attributes=self.visitor_attributes,
            visitor_properties=_merge_persistent_mapping(
                self.visitor_properties,
                visitor_properties,
                replace=replace,
            ),
            default_segments=self.default_segments,
        )

    def set_default_segments(
        self,
        default_segments: Sequence[str],
    ) -> "ContextState":
        """Return a new state with updated default segments."""

        return ContextState(
            visitor_id=self.visitor_id,
            visitor_attributes=self.visitor_attributes,
            visitor_properties=self.visitor_properties,
            default_segments=_freeze_default_segments(default_segments),
        )
