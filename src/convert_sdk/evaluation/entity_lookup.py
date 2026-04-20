"""Config entity lookup helpers for debugging and integration workflows."""

from __future__ import annotations

from typing import Any, Mapping

from ..domain.config_snapshot import ConfigSnapshot


ENTITY_LOOKUP_BY_KEY = {
    "experience": "experiences_by_key",
    "feature": "features_by_key",
    "goal": "goals_by_key",
    "audience": "audiences_by_key",
    "segment": "segments_by_key",
}

ENTITY_LOOKUP_BY_ID = {
    "experience": "experiences_by_id",
    "feature": "features_by_id",
    "goal": "goals_by_id",
    "audience": "audiences_by_id",
    "segment": "segments_by_id",
}


def get_entity_by_key(
    snapshot: ConfigSnapshot,
    entity_type: str,
    key: str,
) -> Mapping[str, Any] | None:
    """Return the matching config entity by key or ``None``."""

    normalized_type = _normalize_entity_type(entity_type)
    normalized_key = _normalize_lookup_value(key, "key")
    if normalized_type == "variation":
        return _lookup_variation_by_key(snapshot, normalized_key)

    index_name = ENTITY_LOOKUP_BY_KEY.get(normalized_type)
    if index_name is None:
        return None
    return getattr(snapshot, index_name).get(normalized_key)


def get_entity_by_id(
    snapshot: ConfigSnapshot,
    entity_type: str,
    entity_id: str,
) -> Mapping[str, Any] | None:
    """Return the matching config entity by id or ``None``."""

    normalized_type = _normalize_entity_type(entity_type)
    normalized_id = _normalize_lookup_value(entity_id, "entity_id")
    if normalized_type == "variation":
        return _lookup_variation_by_id(snapshot, normalized_id)

    index_name = ENTITY_LOOKUP_BY_ID.get(normalized_type)
    if index_name is None:
        return None
    return getattr(snapshot, index_name).get(normalized_id)


def _lookup_variation_by_key(
    snapshot: ConfigSnapshot,
    key: str,
) -> Mapping[str, Any] | None:
    for experience in snapshot.experiences_by_id.values():
        variation = _lookup_variation(experience.get("variations"), "key", key)
        if variation is not None:
            return variation
    return None


def _lookup_variation_by_id(
    snapshot: ConfigSnapshot,
    entity_id: str,
) -> Mapping[str, Any] | None:
    for experience in snapshot.experiences_by_id.values():
        variation = _lookup_variation(experience.get("variations"), "id", entity_id)
        if variation is not None:
            return variation
    return None


def _lookup_variation(
    variations: Any,
    field_name: str,
    expected: str,
) -> Mapping[str, Any] | None:
    if not isinstance(variations, tuple):
        return None
    for variation in variations:
        if not isinstance(variation, Mapping):
            continue
        if str(variation.get(field_name, "")) == expected:
            return variation
    return None


def _normalize_entity_type(entity_type: str) -> str:
    if not isinstance(entity_type, str) or not entity_type.strip():
        raise ValueError("entity_type is required")
    normalized = entity_type.strip().lower()
    singular = normalized[:-1] if normalized.endswith("s") else normalized
    return {"experiment": "experience"}.get(singular, singular)


def _normalize_lookup_value(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()
