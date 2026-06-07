"""Snapshot-backed local feature resolution (minimal foundation, Story 1.6).

Story 1.5's feature-resolution code shipped only on a superseded branch lineage.
Story 1.6 needs a real (not placeholder) feature surface to document and
demonstrate, so this module implements the *minimal* local resolution path it
requires, reusing Story 1.4's experience-selection foundation rather than
duplicating bucketing logic.

Resolution flow for a single feature key:

1. Resolve the declared feature definition from the snapshot (miss -> ``None``).
2. Find the experiences whose variations declare a ``fullStackFeature`` change
   for that feature (its ``data.feature_id``).
3. For each such experience, run Story 1.4's :func:`select_experience` to bucket
   the visitor. If the visitor buckets into a variation that carries the
   feature change, read ``variables_data`` from the change and cast each value
   using the declared feature variable types.
4. Return a typed :class:`~convert_sdk.domain.results.FeatureResult`; any normal
   miss (undeclared feature, unqualified visitor, no bucketed change) returns
   ``None``.

Mirrors the JS SDK's feature resolution (parity:
``../javascript-sdk/packages/js-sdk/src/feature-manager.ts`` ``runFeature`` /
``runFeatures``) minus tracking and persistent visitor-state side effects, which
are explicitly out of scope. Evaluation reads only the immutable snapshot and
caller-scoped attribute dicts; it never mutates either and performs no network
I/O.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from convert_sdk.domain.results import FeatureResult, FeatureStatus
from convert_sdk.evaluation.experiences import select_experience

_FULLSTACK_FEATURE = "fullstackfeature"


def _is_fullstack_feature_change(change: Mapping[str, Any]) -> bool:
    return str(change.get("type", "")).lower() == _FULLSTACK_FEATURE


def _feature_change_for(
    variation: Mapping[str, Any], feature_id: str
) -> Optional[Mapping[str, Any]]:
    """Return the ``fullStackFeature`` change for ``feature_id`` in a variation."""
    for change in variation.get("changes", []) or []:
        if not _is_fullstack_feature_change(change):
            continue
        data = change.get("data") or {}
        if str(data.get("feature_id")) == str(feature_id):
            return data
    return None


def _cast_value(value: Any, declared_type: Optional[str]) -> Any:
    """Cast a raw ``variables_data`` value using the declared variable type.

    Mirrors the JS variable types (``boolean``, ``integer``, ``string``,
    ``json``). Unknown or absent types pass the value through unchanged. Casting
    is best-effort: a value that cannot be cast is returned as-is rather than
    raising, keeping resolution non-throwing for normal config shapes.
    """
    if declared_type is None:
        return value
    kind = declared_type.lower()
    try:
        if kind == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes")
        if kind in ("integer", "int"):
            return int(value)
        if kind in ("float", "double", "number"):
            return float(value)
        if kind == "string":
            return str(value)
        if kind == "json":
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value)
    except (TypeError, ValueError):
        return value
    return value


def _variable_types(feature: Mapping[str, Any]) -> Dict[str, str]:
    types: Dict[str, str] = {}
    for variable in feature.get("variables", []) or []:
        key = variable.get("key")
        var_type = variable.get("type")
        if key is not None and var_type is not None:
            types[str(key)] = str(var_type)
    return types


def _cast_variables(
    raw_variables: Mapping[str, Any], feature: Mapping[str, Any]
) -> Dict[str, Any]:
    types = _variable_types(feature)
    return {
        str(key): _cast_value(value, types.get(str(key)))
        for key, value in (raw_variables or {}).items()
    }


def _experiences_declaring_feature(snapshot: Any, feature_id: str) -> List[Mapping[str, Any]]:
    """Experiences with at least one variation carrying the feature's change."""
    matching: List[Mapping[str, Any]] = []
    for experience in snapshot.experiences:
        for variation in experience.get("variations", []) or []:
            if _feature_change_for(variation, feature_id) is not None:
                matching.append(experience)
                break
    return matching


def resolve_feature(
    feature_key: str,
    snapshot: Any,
    *,
    visitor_id: str,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
) -> Optional[FeatureResult]:
    """Resolve a single feature by key for ``visitor_id``.

    Returns a typed :class:`FeatureResult` when the feature is declared and the
    visitor buckets into a variation carrying its ``fullStackFeature`` change,
    or ``None`` for any normal miss (undeclared feature, unqualified visitor, no
    bucketed change). Never raises for normal evaluation outcomes and performs
    no network I/O.
    """
    if not visitor_id:
        return None

    feature = snapshot.get_feature_by_key(feature_key)
    if feature is None:
        return None

    feature_id = feature.get("id")
    if feature_id is None:
        return None
    feature_id = str(feature_id)

    for experience in _experiences_declaring_feature(snapshot, feature_id):
        experience_key = experience.get("key")
        if experience_key is None:
            continue
        result = select_experience(
            str(experience_key),
            snapshot,
            visitor_id=visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location_attributes,
        )
        if result is None:
            continue
        change = _feature_change_for(result.variation, feature_id)
        if change is None:
            continue
        variables = _cast_variables(change.get("variables_data") or {}, feature)
        return FeatureResult(
            feature_key=str(feature.get("key", feature_key)),
            feature_id=feature_id,
            status=FeatureStatus.ENABLED,
            variables=variables,
            experience_key=str(experience_key),
            variation_key=result.variation_key,
        )

    return None


def resolve_features(
    snapshot: Any,
    *,
    visitor_id: str,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    location_attributes: Optional[Mapping[str, Any]] = None,
) -> List[FeatureResult]:
    """Resolve all applicable features for ``visitor_id``.

    Returns one typed result per declared feature the visitor resolves to an
    ``ENABLED`` state; features the visitor does not bucket into are omitted (no
    ``None`` entries). Evaluation stays local to the snapshot — no network I/O.
    """
    results: List[FeatureResult] = []
    for feature in snapshot.features:
        key = feature.get("key")
        if key is None:
            continue
        result = resolve_feature(
            str(key),
            snapshot,
            visitor_id=visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location_attributes,
        )
        if result is not None:
            results.append(result)
    return results
