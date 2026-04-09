"""Visitor-scoped state foundation for reusable SDK contexts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .config_snapshot import freeze_mapping, freeze_value


EMPTY_VISITOR_ATTRIBUTES = MappingProxyType({})


def _freeze_visitor_attributes(
    visitor_attributes: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if visitor_attributes is None:
        return EMPTY_VISITOR_ATTRIBUTES
    if not isinstance(visitor_attributes, Mapping):
        raise TypeError("visitor_attributes must be a mapping")
    return freeze_mapping(visitor_attributes)


def merge_visitor_attributes(
    stored_attributes: Mapping[str, Any],
    request_attributes: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    if request_attributes is None:
        return stored_attributes
    if not isinstance(request_attributes, Mapping):
        raise TypeError("request_attributes must be a mapping")

    merged_attributes = dict(stored_attributes)
    for key, value in request_attributes.items():
        merged_attributes[str(key)] = freeze_value(value)
    return MappingProxyType(merged_attributes)


@dataclass(frozen=True)
class ContextState:
    """Immutable visitor-scoped state for a reusable SDK context."""

    visitor_id: str
    visitor_attributes: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        visitor_id: str,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
    ) -> "ContextState":
        return cls(
            visitor_id=visitor_id,
            visitor_attributes=_freeze_visitor_attributes(visitor_attributes),
        )

    def resolve_visitor_attributes(
        self,
        request_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Merge stored visitor attributes with request-scoped overrides."""

        return merge_visitor_attributes(self.visitor_attributes, request_attributes)
