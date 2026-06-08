"""Snapshot-backed experience selection for local evaluation (Story 1.4).

Selects a variation for a visitor in a single experience by:

1. Resolving the experience from the immutable snapshot (miss -> ``None``).
2. Qualifying the visitor against the experience's audience/location rules
   (:func:`convert_sdk.evaluation.rules.qualifies`) — unqualified -> ``None``.
3. Building the variation bucket map (RUNNING variations with
   ``traffic_allocation > 0``; a missing/NaN allocation means full 100% traffic)
   and selecting deterministically via the bucketing helpers
   (:mod:`convert_sdk.evaluation.bucketing`).

Mirrors the JS SDK's ``_retrieveBucketing``
(``../javascript-sdk/packages/data/src/data-manager.ts``) minus the
storage/tracking side effects, which are explicitly out of scope for this
story. All normal misses return ``None`` — never an exception. Selection reads
only the immutable snapshot and caller-scoped attribute dicts; it never mutates
either.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation.bucketing import (
    get_bucket_value_for_visitor,
    select_bucket,
)
from convert_sdk.evaluation.rules import qualifies

_RUNNING = "running"


def _is_running(variation: Mapping[str, Any]) -> bool:
    status = variation.get("status")
    if status is None:
        return True
    return str(status).lower() == _RUNNING


def _has_traffic(variation: Mapping[str, Any]) -> bool:
    allocation = variation.get("traffic_allocation")
    if allocation is None:
        # No allocation declared means 100% traffic (JS isNaN branch).
        return True
    try:
        numeric = float(allocation)
    except (TypeError, ValueError):
        return True
    if math.isnan(numeric):
        return True
    return numeric > 0


def _build_buckets(experience: Mapping[str, Any]) -> "dict[str, float]":
    """Build a ``{variation_id: traffic_percentage}`` map for active variations."""
    buckets: "dict[str, float]" = {}
    for variation in experience.get("variations", []) or []:
        if not _is_running(variation):
            continue
        if not _has_traffic(variation):
            continue
        variation_id = variation.get("id")
        if not variation_id:
            continue
        allocation = variation.get("traffic_allocation")
        try:
            percentage = float(allocation)
            if math.isnan(percentage):
                percentage = 100.0
        except (TypeError, ValueError):
            percentage = 100.0
        buckets[str(variation_id)] = percentage
    return buckets


def select_experience(
    experience_key: str,
    snapshot: Any,
    *,
    visitor_id: str,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
) -> Optional[ExperienceResult]:
    """Select a variation for ``visitor_id`` in the experience ``experience_key``.

    Returns a typed :class:`ExperienceResult` for a qualified visitor that
    buckets into an active variation, or ``None`` for any normal miss (missing
    experience, unqualified visitor, no active variation, or no bucket).
    """
    if not visitor_id:
        return None

    experience = snapshot.get_experience_by_key(experience_key)
    if experience is None:
        return None

    if not qualifies(
        experience,
        snapshot,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
    ):
        return None

    experience_id = experience.get("id")
    if not experience_id:
        return None

    buckets = _build_buckets(experience)
    if not buckets:
        return None

    bucket_value = get_bucket_value_for_visitor(
        visitor_id, experience_id=str(experience_id)
    )
    variation_id = select_bucket(buckets, bucket_value)
    if variation_id is None:
        return None

    variation = _find_variation(experience, variation_id)
    if variation is None:
        return None

    return ExperienceResult(
        experience_key=str(experience.get("key", experience_key)),
        experience_id=str(experience_id),
        variation_id=str(variation_id),
        variation_key=(
            str(variation.get("key")) if variation.get("key") is not None else None
        ),
        variation=variation,
    )


def _find_variation(
    experience: Mapping[str, Any], variation_id: str
) -> Optional[Mapping[str, Any]]:
    variations: Sequence[Mapping[str, Any]] = experience.get("variations", []) or []
    for variation in variations:
        if str(variation.get("id")) == str(variation_id):
            return variation
    return None
