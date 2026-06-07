"""Typed result models for local experience evaluation (Story 1.4).

Evaluation returns typed Python result objects — never raw config
dictionaries. Normal no-match outcomes are represented as ``None`` (single
evaluation) or empty collections (bulk evaluation) by the callers in
``evaluation/`` and :mod:`convert_sdk.context`, not by sentinel result values.

:class:`ExperienceResult` is a frozen dataclass; its ``variation`` payload is a
read-only mapping so callers cannot mutate the snapshot-owned variation config
through the result.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ExperienceResult:
    """The typed outcome of bucketing a visitor into one experience variation.

    Attributes:
        experience_key: The evaluated experience's key.
        experience_id: The evaluated experience's id.
        variation_key: The selected variation's key (may be ``None`` if the
            variation config has no key).
        variation_id: The selected variation's id.
        variation: A read-only view of the selected variation's config. Story
            1.5 reads feature/variable data from here; this story does not
            interpret the payload.
    """

    experience_key: str
    experience_id: str
    variation_id: str
    variation_key: Optional[str] = None
    variation: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Wrap the variation payload so the typed result cannot be used to
        # mutate snapshot-owned config.
        if not isinstance(self.variation, MappingProxyType):
            object.__setattr__(
                self, "variation", MappingProxyType(dict(self.variation))
            )


class FeatureStatus(str, enum.Enum):
    """The resolved state of a feature for a visitor.

    Mirrors the JS SDK's ``FeatureStatus`` (parity:
    ``../javascript-sdk/packages/enums``). A feature is ``ENABLED`` when the
    visitor buckets into a variation that carries a ``fullStackFeature`` change
    for it; otherwise normal misses are represented as ``None`` by the callers
    (``Context.run_feature`` / ``run_features``) rather than a ``DISABLED``
    sentinel result, keeping the Pythonic no-result convention consistent with
    experience evaluation. ``DISABLED`` remains available for callers that
    explicitly model a declared-but-unbucketed feature.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class FeatureResult:
    """The typed outcome of resolving one feature for a visitor.

    Resolved locally from the visitor's selected variation: the SDK reads the
    variation's ``fullStackFeature`` change(s), matches the ``feature_id`` back
    to a declared feature definition in the snapshot, and casts each variable
    value using the feature's declared variable types.

    Attributes:
        feature_key: The declared feature's key.
        feature_id: The declared feature's id.
        status: :class:`FeatureStatus` — ``ENABLED`` for a resolved feature.
        variables: A read-only mapping of resolved, type-cast feature variables.
        experience_key: The key of the experience whose variation supplied the
            feature change (``None`` if the source experience has no key).
        variation_key: The selected variation's key (``None`` if unset).
    """

    feature_key: str
    feature_id: str
    status: FeatureStatus = FeatureStatus.ENABLED
    variables: Mapping[str, Any] = field(default_factory=dict)
    experience_key: Optional[str] = None
    variation_key: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.variables, MappingProxyType):
            object.__setattr__(
                self, "variables", MappingProxyType(dict(self.variables))
            )
