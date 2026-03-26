from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.data import DataManager
from convertcom_sdk.enums import BucketingError, FeatureStatus, RuleError, VariationChangeType
from convertcom_sdk.utils.type_utils import cast_type


class FeatureManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        data_manager: DataManager,
    ) -> None:
        del config
        self._data_manager = data_manager

    def get_list(self) -> list[dict[str, Any]]:
        return self._data_manager.get_entities_list("features")

    def get_list_as_object(self, field: str = "id") -> dict[str, dict[str, Any]]:
        return self._data_manager.get_entities_list_object("features", field)

    def get_feature(self, key: str) -> dict[str, Any] | None:
        return self._data_manager.get_entity(key, "features")

    def get_feature_by_id(self, entity_id: str) -> dict[str, Any] | None:
        return self._data_manager.get_entity_by_id(entity_id, "features")

    def get_features(self, keys: list[str]) -> list[dict[str, Any]]:
        return self._data_manager.get_items_by_keys(keys, "features")

    def get_feature_variable_type(self, key: str, variable_name: str) -> str | None:
        feature = self.get_feature(key) or {}
        for variable in feature.get("variables") or []:
            if variable.get("key") == variable_name:
                return variable.get("type")
        return None

    def get_feature_variable_type_by_id(self, entity_id: str, variable_name: str) -> str | None:
        feature = self.get_feature_by_id(entity_id) or {}
        for variable in feature.get("variables") or []:
            if variable.get("key") == variable_name:
                return variable.get("type")
        return None

    def is_feature_declared(self, key: str) -> bool:
        return bool(self._data_manager.get_entity(key, "features"))

    def run_feature(
        self,
        visitor_id: str,
        feature_key: str,
        attributes: Mapping[str, Any],
        experience_keys: list[str] | None = None,
    ) -> Any:
        declared = self._data_manager.get_entity(feature_key, "features")
        if not declared:
            return {"key": feature_key, "status": FeatureStatus.DISABLED.value}
        features = self.run_features(
            visitor_id,
            attributes,
            {"features": [feature_key], "experiences": experience_keys},
        )
        if features:
            return features[0] if len(features) == 1 else features
        return {
            "id": declared.get("id"),
            "name": declared.get("name"),
            "key": feature_key,
            "status": FeatureStatus.DISABLED.value,
        }

    def is_feature_enabled(
        self,
        visitor_id: str,
        feature_key: str,
        attributes: Mapping[str, Any],
        experience_keys: list[str] | None = None,
    ) -> bool:
        if not self._data_manager.get_entity(feature_key, "features"):
            return False
        features = self.run_features(
            visitor_id,
            attributes,
            {"features": [feature_key], "experiences": experience_keys},
        )
        return bool(features)

    def run_feature_by_id(
        self,
        visitor_id: str,
        feature_id: str,
        attributes: Mapping[str, Any],
        experience_ids: list[str] | None = None,
    ) -> Any:
        declared = self._data_manager.get_entity_by_id(feature_id, "features")
        if not declared:
            return {"id": feature_id, "status": FeatureStatus.DISABLED.value}
        experience_keys = None
        if experience_ids:
            experience_keys = [item.get("key") for item in self._data_manager.get_entities_by_ids(experience_ids, "experiences")]
        features = self.run_features(
            visitor_id,
            attributes,
            {"features": [declared.get("key")], "experiences": experience_keys},
        )
        if features:
            return features[0] if len(features) == 1 else features
        return {
            "id": feature_id,
            "name": declared.get("name"),
            "key": declared.get("key"),
            "status": FeatureStatus.DISABLED.value,
        }

    def run_features(
        self,
        visitor_id: str,
        attributes: Mapping[str, Any],
        filter_by: Mapping[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        filter_by = filter_by or {}
        type_casting = attributes.get("typeCasting", True)
        declared_features = self.get_list_as_object("id")
        bucketed_features: list[dict[str, Any]] = []

        if filter_by.get("experiences"):
            experiences = self._data_manager.get_entities(filter_by["experiences"], "experiences")
        else:
            experiences = self._data_manager.get_entities_list("experiences")

        bucketed_variations = []
        for experience in experiences:
            variation = self._data_manager.get_bucketing(visitor_id, experience.get("key"), attributes)
            if isinstance(variation, dict):
                bucketed_variations.append(variation)

        for bucketed_variation in bucketed_variations:
            for change in bucketed_variation.get("changes") or []:
                if change.get("type") != VariationChangeType.FULLSTACK_FEATURE.value:
                    continue
                changes = change.get("data") or {}
                feature_id = changes.get("feature_id")
                if not feature_id:
                    continue
                feature = declared_features.get(str(feature_id))
                if not feature:
                    continue
                if filter_by.get("features") and feature.get("key") not in filter_by["features"]:
                    continue

                variables = dict(changes.get("variables_data") or {})
                if type_casting:
                    for variable_name, variable_value in list(variables.items()):
                        variable_definition = next(
                            (
                                item
                                for item in feature.get("variables") or []
                                if item.get("key") == variable_name
                            ),
                            None,
                        )
                        if variable_definition and variable_definition.get("type"):
                            variables[variable_name] = cast_type(
                                variable_value, variable_definition["type"]
                            )

                bucketed_features.append(
                    {
                        "experienceId": bucketed_variation.get("experienceId"),
                        "experienceName": bucketed_variation.get("experienceName"),
                        "experienceKey": bucketed_variation.get("experienceKey"),
                        "key": feature.get("key"),
                        "name": feature.get("name"),
                        "id": str(feature_id),
                        "status": FeatureStatus.ENABLED.value,
                        "variables": variables,
                    }
                )

        if not filter_by.get("features"):
            bucketed_feature_ids = {item["id"] for item in bucketed_features}
            for feature in declared_features.values():
                if feature.get("id") not in bucketed_feature_ids:
                    bucketed_features.append(
                        {
                            "id": feature.get("id"),
                            "name": feature.get("name"),
                            "key": feature.get("key"),
                            "status": FeatureStatus.DISABLED.value,
                        }
                    )
        return bucketed_features

    def cast_type(self, value: object, kind: str) -> object:
        return cast_type(value, kind)
