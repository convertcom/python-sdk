"""Typed public SDK result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .config_snapshot import freeze_mapping


EMPTY_VARIABLES = MappingProxyType({})
EMPTY_CONVERSION_DATA = MappingProxyType({})
EMPTY_BUCKETING_DATA = MappingProxyType({})


def freeze_variables(variables: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Freeze feature variables into an immutable mapping."""

    if not variables:
        return EMPTY_VARIABLES
    return freeze_mapping(variables)


def freeze_conversion_data(
    conversion_data: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Freeze conversion data into an immutable mapping."""

    if not conversion_data:
        return EMPTY_CONVERSION_DATA
    return freeze_mapping(conversion_data)


def freeze_bucketing_data(
    bucketing_data: Mapping[str, str] | None,
) -> Mapping[str, str]:
    """Freeze bucketing attribution data into an immutable mapping."""

    if not bucketing_data:
        return EMPTY_BUCKETING_DATA
    return MappingProxyType({str(key): str(value) for key, value in bucketing_data.items()})


class FeatureStatus(str, Enum):
    """Status values for resolved feature results."""

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ExperienceResult:
    """Typed outcome for a bucketed experience variation."""

    experience_id: str
    experience_key: str
    experience_name: str | None
    variation_id: str
    variation_key: str
    variation_name: str | None
    bucket_value: int


@dataclass(frozen=True)
class FeatureResult:
    """Typed outcome for a resolved feature decision."""

    feature_id: str
    feature_key: str
    feature_name: str | None
    status: FeatureStatus
    variables: Mapping[str, Any]
    experience_id: str | None = None
    experience_key: str | None = None
    experience_name: str | None = None
    variation_id: str | None = None
    variation_key: str | None = None


@dataclass(frozen=True)
class ConversionEvent:
    """Typed conversion event created from a visitor context."""

    visitor_id: str
    goal_id: str
    goal_key: str
    goal_name: str | None = None
    account_id: str | None = None
    project_id: str | None = None
    conversion_data: Mapping[str, Any] = EMPTY_CONVERSION_DATA
    bucketing_data: Mapping[str, str] = EMPTY_BUCKETING_DATA
    event_type: str = "conversion"


@dataclass(frozen=True)
class ConversionResult:
    """Typed outcome for queued conversion events."""

    events: tuple[ConversionEvent, ...] = ()
    duplicate_prevented: bool = False
    queued_event_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        if self.queued_event_count == 0 and self.events:
            object.__setattr__(self, "queued_event_count", len(self.events))

    @property
    def event(self) -> ConversionEvent | None:
        """Return the most useful event for callers expecting a single result."""

        if not self.events:
            return None
        for event in reversed(self.events):
            if event.conversion_data:
                return event
        return self.events[0]


@dataclass(frozen=True)
class TrackingFlushResult:
    """Typed outcome for explicit tracking queue release."""

    attempted: bool
    delivered_event_count: int
    delivered_batch_count: int
    remaining_event_count: int
    reason: str | None = None
