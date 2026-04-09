"""Typed public evaluation results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .config_snapshot import freeze_mapping


EMPTY_VARIABLES = MappingProxyType({})


def freeze_variables(variables: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Freeze feature variables into an immutable mapping."""

    if not variables:
        return EMPTY_VARIABLES
    return freeze_mapping(variables)


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

