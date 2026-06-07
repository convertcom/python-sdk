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


class ConversionStatus(str, enum.Enum):
    """The outcome of attempting to track a conversion (Story 2.1).

    Mirrors the typed-result-with-status-enum precedent set by
    :class:`FeatureStatus`. ``QUEUED`` means a conversion event was created and
    associated with the visitor + resolved goal. ``GOAL_NOT_FOUND`` is the
    diagnosable NON-EXCEPTION outcome (FR50) for a goal key absent from the
    loaded config — distinguishable from success without ``try``/``except``.
    """

    QUEUED = "queued"
    GOAL_NOT_FOUND = "goal_not_found"


@dataclass(frozen=True)
class ConversionEvent:
    """An in-process conversion event tied to a visitor and resolved goal.

    Story 2.1 creates this locally from the current immutable snapshot and
    visitor state — it carries the stable goal identity needed for later payload
    shaping (Story 2.2 owns ``tracking/payloads.py``). No raw outbound payload
    serialization happens here, and no network I/O is performed.

    Attributes:
        visitor_id: The visitor the conversion is attributed to.
        goal_id: The resolved goal's id (stable downstream-attribution identity).
        goal_key: The resolved goal's key (the public tracking handle / JS parity).
    """

    visitor_id: str
    goal_id: str
    goal_key: str


@dataclass(frozen=True)
class ConversionResult:
    """The typed outcome of :meth:`convert_sdk.context.Context.track_conversion`.

    Always returned (never raised) for both success and the unknown-goal miss so
    callers diagnose the outcome via :attr:`status` alone (FR50). On
    ``QUEUED`` the :attr:`event` carries the created
    :class:`ConversionEvent`; on ``GOAL_NOT_FOUND`` the event is ``None`` and
    :attr:`goal_id` is ``None``.

    Attributes:
        status: :class:`ConversionStatus` — ``QUEUED`` or ``GOAL_NOT_FOUND``.
        goal_key: The goal key the caller asked to track (always echoed back so
            an unknown-goal result remains diagnosable).
        goal_id: The resolved goal's id, or ``None`` when the goal was not found.
        visitor_id: The visitor the tracking call was made for.
        event: The created :class:`ConversionEvent`, or ``None`` on a miss.
    """

    status: ConversionStatus
    goal_key: str
    goal_id: Optional[str]
    visitor_id: str
    event: Optional[ConversionEvent] = None
