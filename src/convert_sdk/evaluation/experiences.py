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
    build_bucket_ranges,
    get_bucket_value_for_visitor,
    select_bucket,
    select_bucket_anchored,
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


def _is_anchored_layout(experience: Mapping[str, Any]) -> bool:
    """Return ``True`` iff ``experience`` gates the anchored layout (bucketing
    contract v12; qs-01-anchored-bucketing-layout.md).

    Mirrors the JS reference's ``Number(experience.version) > 11``: numeric
    strings coerce the same way JS ``Number()`` does (``"12"`` -> anchored),
    while a missing, ``NaN``, or non-numeric ``version`` routes to the
    existing packed layout — every currently-served production experience is
    stamped ``version: 11`` and must keep resolving through the packed walk
    (the inert-on-ship guarantee). Uses the same float-coercion shape as
    :func:`_has_traffic` rather than an ``isinstance`` check, so numeric
    strings are honored exactly like the JS ``Number()`` coercion.
    """
    version = experience.get("version")
    if version is None:
        return False
    try:
        numeric = float(version)
    except (TypeError, ValueError):
        return False
    if math.isnan(numeric):
        return False
    return numeric > 11


def _build_variation_allocations(
    experience: Mapping[str, Any],
) -> "list[dict[str, Any]]":
    """Build the ordered anchored-layout allocation list for ``experience``.

    Unlike :func:`_build_buckets` (the packed layout's builder), inactive and
    zero-allocation variations are **not** dropped here — the anchored
    algorithm needs every entry's allocation weight (active or not) to walk
    the cumulative anchors, so stopping one arm never moves its neighbours'
    anchors (see :func:`convert_sdk.evaluation.bucketing.build_bucket_ranges`).
    Only entries missing an ``id`` are skipped. Mirrors the JS reference's
    ``_buildVariationAllocations``
    (``../javascript-sdk`` branch ``feat/anchored-bucketing-layout``,
    ``packages/data/src/data-manager.ts``): ``allocation`` defaults to
    ``100.0`` when the declared ``traffic_allocation`` is absent, non-numeric,
    or ``NaN`` (never re-interpreting an explicit ``0`` as ``100``), and
    ``active`` reuses the existing :func:`_is_running` / :func:`_has_traffic`
    helpers, which already match the JS ``status``/``ta`` semantics.
    """
    allocations: "list[dict[str, Any]]" = []
    for variation in experience.get("variations", []) or []:
        variation_id = variation.get("id")
        if not variation_id:
            continue
        raw_allocation = variation.get("traffic_allocation")
        try:
            percentage = float(raw_allocation)
            if math.isnan(percentage):
                percentage = 100.0
        except (TypeError, ValueError):
            percentage = 100.0
        allocations.append(
            {
                "id": str(variation_id),
                "allocation": percentage,
                "active": _is_running(variation) and _has_traffic(variation),
            }
        )
    return allocations


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

    bucket_value = get_bucket_value_for_visitor(
        visitor_id, experience_id=str(experience_id)
    )

    if _is_anchored_layout(experience):
        allocations = _build_variation_allocations(experience)
        ranges = build_bucket_ranges(allocations)
        variation_id = select_bucket_anchored(ranges, bucket_value)
    else:
        buckets = _build_buckets(experience)
        if not buckets:
            return None
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
