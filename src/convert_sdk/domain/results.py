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
