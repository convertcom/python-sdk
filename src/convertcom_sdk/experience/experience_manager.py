from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.data import DataManager


class ExperienceManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        data_manager: DataManager,
    ) -> None:
        del config
        self._data_manager = data_manager

    def get_list(self) -> list[dict[str, Any]]:
        return self._data_manager.get_entities_list("experiences")

    def get_experience(self, key: str) -> dict[str, Any] | None:
        return self._data_manager.get_entity(key, "experiences")

    def get_experience_by_id(self, entity_id: str) -> dict[str, Any] | None:
        return self._data_manager.get_entity_by_id(entity_id, "experiences")

    def get_experiences(self, keys: list[str]) -> list[dict[str, Any]]:
        return self._data_manager.get_items_by_keys(keys, "experiences")

    def select_variation(
        self,
        visitor_id: str,
        experience_key: str,
        attributes: Mapping[str, Any],
    ) -> Any:
        return self._data_manager.get_bucketing(visitor_id, experience_key, attributes)

    def select_variation_by_id(
        self,
        visitor_id: str,
        experience_id: str,
        attributes: Mapping[str, Any],
    ) -> Any:
        return self._data_manager.get_bucketing_by_id(visitor_id, experience_id, attributes)

    def select_variations(
        self,
        visitor_id: str,
        attributes: Mapping[str, Any],
    ) -> list[Any]:
        variations = []
        for experience in self.get_list():
            variation = self.select_variation(visitor_id, experience.get("key"), attributes)
            if isinstance(variation, dict):
                variations.append(variation)
        return variations

    def get_variation(self, experience_key: str, variation_key: str) -> dict[str, Any] | None:
        return self._data_manager.get_sub_item(
            "experiences",
            experience_key,
            "variations",
            variation_key,
            "key",
            "key",
        )

    def get_variation_by_id(self, experience_id: str, variation_id: str) -> dict[str, Any] | None:
        return self._data_manager.get_sub_item(
            "experiences",
            experience_id,
            "variations",
            variation_id,
            "id",
            "id",
        )
