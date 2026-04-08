"""Immutable config snapshot foundation."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


def freeze_value(value: Any) -> Any:
    """Recursively freeze config payloads into immutable Python structures."""

    if isinstance(value, Mapping):
        return freeze_mapping(value)
    if isinstance(value, list):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(item) for item in value)
    return value


def freeze_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen_items = {str(key): freeze_value(value) for key, value in mapping.items()}
    return MappingProxyType(frozen_items)


def _extract_key(value: Mapping[str, Any]) -> str | None:
    for candidate in ("key", "id", "slug"):
        extracted = value.get(candidate)
        if extracted not in (None, ""):
            return str(extracted)
    return None


def build_entity_index(values: Any) -> Mapping[str, Mapping[str, Any]]:
    index: MutableMapping[str, Mapping[str, Any]] = {}

    if isinstance(values, Mapping):
        items: Iterable[tuple[Any, Any]] = values.items()
        for key, value in items:
            if isinstance(value, Mapping):
                index[str(key)] = freeze_mapping(value)
        return MappingProxyType(dict(index))

    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        for value in values:
            if not isinstance(value, Mapping):
                continue
            key = _extract_key(value)
            if key is None:
                continue
            index[key] = freeze_mapping(value)

    return MappingProxyType(dict(index))


@dataclass(frozen=True)
class ConfigSnapshot:
    """Immutable normalized config snapshot with parity-oriented indexes."""

    raw_data: Mapping[str, Any]
    account_id: str | None
    project_id: str | None
    project: Mapping[str, Any]
    experiences_by_key: Mapping[str, Mapping[str, Any]]
    features_by_key: Mapping[str, Mapping[str, Any]]
    goals_by_key: Mapping[str, Mapping[str, Any]]
    audiences_by_key: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_config_data(cls, config_data: Mapping[str, Any]) -> "ConfigSnapshot":
        frozen_data = freeze_mapping(config_data)
        project = frozen_data.get("project")
        project_mapping = project if isinstance(project, Mapping) else MappingProxyType({})

        return cls(
            raw_data=frozen_data,
            account_id=str(frozen_data["account_id"]) if "account_id" in frozen_data else None,
            project_id=str(project_mapping["id"]) if "id" in project_mapping else None,
            project=project_mapping,
            experiences_by_key=build_entity_index(frozen_data.get("experiences", ())),
            features_by_key=build_entity_index(frozen_data.get("features", ())),
            goals_by_key=build_entity_index(frozen_data.get("goals", ())),
            audiences_by_key=build_entity_index(frozen_data.get("audiences", ())),
        )
