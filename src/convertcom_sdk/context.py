from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.enums import EntityType, SystemEvents
from convertcom_sdk.utils.object_utils import object_deep_merge, object_not_empty

ENTITY_TYPE_MAP = {
    EntityType.AUDIENCE.value: "audiences",
    EntityType.LOCATION.value: "locations",
    EntityType.SEGMENT.value: "segments",
    EntityType.FEATURE.value: "features",
    EntityType.GOAL.value: "goals",
    EntityType.EXPERIENCE.value: "experiences",
}


def _normalize_entity_type(entity_type: EntityType | str) -> EntityType:
    if isinstance(entity_type, EntityType):
        return entity_type
    return EntityType(entity_type)


class Context:
    def __init__(
        self,
        config: Mapping[str, Any] | None,
        visitor_id: str | None,
        *,
        event_manager: Any,
        experience_manager: Any,
        feature_manager: Any,
        segments_manager: Any,
        data_manager: Any,
        api_manager: Any,
        visitor_properties: Mapping[str, Any] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._visitor_id = visitor_id
        self._event_manager = event_manager
        self._experience_manager = experience_manager
        self._feature_manager = feature_manager
        self._segments_manager = segments_manager
        self._data_manager = data_manager
        self._api_manager = api_manager
        self._environment = self._config.get("environment")
        self._visitor_properties: dict[str, Any] = {}
        if object_not_empty(visitor_properties):
            filtered = self._data_manager.filter_report_segments(visitor_properties)
            if filtered["properties"]:
                self._visitor_properties = dict(filtered["properties"])
            self._segments_manager.put_segments(visitor_id, visitor_properties)

    def _has_visitor(self) -> bool:
        return bool(self._visitor_id)

    def _base_attributes(
        self,
        attributes: Mapping[str, Any] | None = None,
        *,
        type_casting_default: bool | None = None,
    ) -> dict[str, Any]:
        attributes = dict(attributes or {})
        result = {
            "visitorProperties": self.get_visitor_properties(attributes.get("visitorProperties")),
            "locationProperties": attributes.get("locationProperties"),
            "updateVisitorProperties": attributes.get("updateVisitorProperties"),
            "environment": attributes.get("environment") or self._environment,
        }
        if type_casting_default is not None:
            result["typeCasting"] = attributes.get("typeCasting", type_casting_default)
        if "forceVariationId" in attributes:
            result["forceVariationId"] = attributes.get("forceVariationId")
        return result

    def run_experience(self, experience_key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        if not self._has_visitor():
            return None
        bucketed_variation = self._experience_manager.select_variation(
            self._visitor_id,
            experience_key,
            self._base_attributes(attributes),
        )
        if isinstance(bucketed_variation, Mapping):
            self._event_manager.fire(
                SystemEvents.BUCKETING,
                {
                    "visitorId": self._visitor_id,
                    "experienceKey": experience_key,
                    "variationKey": bucketed_variation.get("key"),
                },
                None,
                True,
            )
        return bucketed_variation

    def runExperience(self, experience_key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.run_experience(experience_key, attributes)

    def run_experiences(self, attributes: Mapping[str, Any] | None = None) -> list[Any] | None:
        if not self._has_visitor():
            return None
        bucketed_variations = self._experience_manager.select_variations(
            self._visitor_id,
            self._base_attributes(attributes),
        )
        for bucketed_variation in bucketed_variations:
            self._event_manager.fire(
                SystemEvents.BUCKETING,
                {
                    "visitorId": self._visitor_id,
                    "experienceKey": bucketed_variation.get("experienceKey"),
                    "variationKey": bucketed_variation.get("key"),
                },
                None,
                True,
            )
        return bucketed_variations

    def runExperiences(self, attributes: Mapping[str, Any] | None = None) -> list[Any] | None:
        return self.run_experiences(attributes)

    def run_feature(self, key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        if not self._has_visitor():
            return None
        attributes = dict(attributes or {})
        bucketed_feature = self._feature_manager.run_feature(
            self._visitor_id,
            key,
            self._base_attributes(attributes, type_casting_default=True),
            attributes.get("experienceKeys"),
        )
        items = bucketed_feature if isinstance(bucketed_feature, list) else [bucketed_feature]
        for item in [feature for feature in items if isinstance(feature, Mapping)]:
            self._event_manager.fire(
                SystemEvents.BUCKETING,
                {
                    "visitorId": self._visitor_id,
                    "experienceKey": item.get("experienceKey"),
                    "featureKey": key,
                    "status": item.get("status"),
                },
                None,
                True,
            )
        return bucketed_feature

    def runFeature(self, key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.run_feature(key, attributes)

    def run_features(self, attributes: Mapping[str, Any] | None = None) -> list[Any] | None:
        if not self._has_visitor():
            return None
        bucketed_features = self._feature_manager.run_features(
            self._visitor_id,
            self._base_attributes(attributes, type_casting_default=True),
        )
        for item in [feature for feature in bucketed_features if isinstance(feature, Mapping)]:
            self._event_manager.fire(
                SystemEvents.BUCKETING,
                {
                    "visitorId": self._visitor_id,
                    "experienceKey": item.get("experienceKey"),
                    "featureKey": item.get("key"),
                    "status": item.get("status"),
                },
                None,
                True,
            )
        return bucketed_features

    def runFeatures(self, attributes: Mapping[str, Any] | None = None) -> list[Any] | None:
        return self.run_features(attributes)

    def track_conversion(self, goal_key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        if not self._has_visitor():
            return None
        attributes = dict(attributes or {})
        goal_data = attributes.get("conversionData")
        if goal_data is not None and not isinstance(goal_data, list):
            return None
        result = self._data_manager.convert(
            self._visitor_id,
            goal_key,
            attributes.get("ruleData"),
            goal_data,
            self._segments_manager.get_segments(self._visitor_id),
            attributes.get("conversionSetting"),
        )
        if result:
            self._event_manager.fire(
                SystemEvents.CONVERSION,
                {"visitorId": self._visitor_id, "goalKey": goal_key},
                None,
                True,
            )
        return result

    def trackConversion(self, goal_key: str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.track_conversion(goal_key, attributes)

    def set_default_segments(self, segments: Mapping[str, Any]) -> None:
        self._segments_manager.put_segments(self._visitor_id, segments)

    def setDefaultSegments(self, segments: Mapping[str, Any]) -> None:
        self.set_default_segments(segments)

    def set_custom_segments(self, segment_keys: list[str] | str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.run_custom_segments(segment_keys, attributes)

    def setCustomSegments(self, segment_keys: list[str] | str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.set_custom_segments(segment_keys, attributes)

    def run_custom_segments(self, segment_keys: list[str] | str, attributes: Mapping[str, Any] | None = None) -> Any:
        if not self._has_visitor():
            return None
        keys = [segment_keys] if isinstance(segment_keys, str) else list(segment_keys)
        return self._segments_manager.select_custom_segments(
            self._visitor_id,
            keys,
            self.get_visitor_properties((attributes or {}).get("ruleData")),
        )

    def runCustomSegments(self, segment_keys: list[str] | str, attributes: Mapping[str, Any] | None = None) -> Any:
        return self.run_custom_segments(segment_keys, attributes)

    def update_visitor_properties(self, visitor_id: str, visitor_properties: Mapping[str, Any]) -> None:
        self._data_manager.put_data(visitor_id, {"segments": dict(visitor_properties)})

    def updateVisitorProperties(self, visitor_id: str, visitor_properties: Mapping[str, Any]) -> None:
        self.update_visitor_properties(visitor_id, visitor_properties)

    def get_config_entity(self, key: str, entity_type: EntityType | str) -> Any:
        entity_type = _normalize_entity_type(entity_type)
        if entity_type == EntityType.VARIATION:
            for experience in self._data_manager.get_entities_list("experiences"):
                variation = self._data_manager.get_sub_item(
                    "experiences",
                    experience.get("key"),
                    "variations",
                    key,
                    "key",
                    "key",
                )
                if variation:
                    return variation
            return None
        return self._data_manager.get_entity(key, ENTITY_TYPE_MAP[entity_type.value])

    def getConfigEntity(self, key: str, entity_type: EntityType | str) -> Any:
        return self.get_config_entity(key, entity_type)

    def get_config_entity_by_id(self, entity_id: str, entity_type: EntityType | str) -> Any:
        entity_type = _normalize_entity_type(entity_type)
        if entity_type == EntityType.VARIATION:
            for experience in self._data_manager.get_entities_list("experiences"):
                variation = self._data_manager.get_sub_item(
                    "experiences",
                    experience.get("id"),
                    "variations",
                    entity_id,
                    "id",
                    "id",
                )
                if variation:
                    return variation
            return None
        return self._data_manager.get_entity_by_id(entity_id, ENTITY_TYPE_MAP[entity_type.value])

    def getConfigEntityById(self, entity_id: str, entity_type: EntityType | str) -> Any:
        return self.get_config_entity_by_id(entity_id, entity_type)

    def get_visitor_data(self) -> dict[str, Any]:
        return self._data_manager.get_data(self._visitor_id) or {}

    def getVisitorData(self) -> dict[str, Any]:
        return self.get_visitor_data()

    def release_queues(self, reason: str | None = None) -> Any:
        if self._data_manager.data_store_manager:
            self._data_manager.data_store_manager.release_queue(reason)
        return self._api_manager.release_queue(reason)

    def releaseQueues(self, reason: str | None = None) -> Any:
        return self.release_queues(reason)

    def get_visitor_properties(self, attributes: Mapping[str, Any] | None = None) -> dict[str, Any]:
        store_data = self._data_manager.get_data(self._visitor_id) or {}
        segments = store_data.get("segments") or {}
        visitor_properties = (
            object_deep_merge(self._visitor_properties, dict(attributes or {}))
            if attributes
            else dict(self._visitor_properties)
        )
        return object_deep_merge(segments, visitor_properties)
