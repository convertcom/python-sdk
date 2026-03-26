from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.bucketing import BucketingManager
from convertcom_sdk.data.data_store_manager import DataStoreManager
from convertcom_sdk.enums import BucketingError, RuleError, SegmentsKeys
from convertcom_sdk.rules import RuleManager
from convertcom_sdk.utils.object_utils import object_deep_merge, object_not_empty


class DataManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        bucketing_manager: BucketingManager,
        rule_manager: RuleManager,
        data_store_manager: DataStoreManager | None = None,
        api_manager: Any | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._data = self._config.get("data") or {}
        self._bucketing_manager = bucketing_manager
        self._rule_manager = rule_manager
        self._data_store_manager = data_store_manager
        self._api_manager = api_manager
        self._environment = self._config.get("environment")
        self._account_id = self._data.get("account_id")
        self._project_id = (self._data.get("project") or {}).get("id")
        self._bucketed_visitors: dict[str, dict[str, Any]] = {}

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @data.setter
    def data(self, value: Mapping[str, Any] | None) -> None:
        if self.is_valid_config_data(value):
            self._data = dict(value or {})
            self._account_id = self._data.get("account_id")
            self._project_id = (self._data.get("project") or {}).get("id")

    @property
    def data_store_manager(self) -> DataStoreManager | None:
        return self._data_store_manager

    def set_api_manager(self, api_manager: Any | None) -> None:
        self._api_manager = api_manager

    def reset(self) -> None:
        self._bucketed_visitors = {}

    def is_valid_config_data(self, data: Mapping[str, Any] | None) -> bool:
        if not object_not_empty(data):
            return False
        return bool(
            data.get("error")
            or (data.get("account_id") and (data.get("project") or {}).get("id"))
        )

    def get_store_key(self, visitor_id: str) -> str:
        return f"{self._account_id}-{self._project_id}-{visitor_id}"

    def get_data(self, visitor_id: str) -> dict[str, Any] | None:
        store_key = self.get_store_key(visitor_id)
        memory_data = self._bucketed_visitors.get(store_key) or {}
        if self._data_store_manager:
            stored = self._data_store_manager.get(store_key) or {}
            return object_deep_merge(memory_data, stored)
        return memory_data or None

    def put_data(self, visitor_id: str, new_data: Mapping[str, Any] | None = None) -> None:
        new_data = dict(new_data or {})
        store_key = self.get_store_key(visitor_id)
        current = self.get_data(visitor_id) or {}
        updated = object_deep_merge(current, new_data)
        self._bucketed_visitors[store_key] = updated
        if self._data_store_manager:
            self._data_store_manager.set(store_key, updated)

    def filter_report_segments(
        self, visitor_properties: Mapping[str, Any] | None
    ) -> dict[str, dict[str, Any] | None]:
        visitor_properties = visitor_properties or {}
        segment_keys = {item.value for item in SegmentsKeys}
        segments: dict[str, Any] = {}
        properties: dict[str, Any] = {}
        for key, value in visitor_properties.items():
            if key in segment_keys:
                segments[key] = value
            else:
                properties[key] = value
        return {
            "properties": properties or None,
            "segments": segments or None,
        }

    def get_entities_list(self, entity_type: str) -> list[Any]:
        return list((self._data or {}).get(entity_type) or [])

    def get_entities_list_object(self, entity_type: str, field: str = "id") -> dict[str, Any]:
        return {
            str(entity[field]): entity
            for entity in self.get_entities_list(entity_type)
            if isinstance(entity, Mapping) and field in entity
        }

    def _get_entity_by_field(self, identity: str, entity_type: str, identity_field: str = "key") -> Any:
        for entity in self.get_entities_list(entity_type):
            if isinstance(entity, Mapping) and str(entity.get(identity_field)) == str(identity):
                return entity
        return None

    def get_entity(self, key: str, entity_type: str) -> Any:
        return self._get_entity_by_field(key, entity_type, "key")

    def get_entities(self, keys: list[str], entity_type: str) -> list[Any]:
        return self.get_items_by_keys(keys, entity_type)

    def get_entity_by_id(self, entity_id: str, entity_type: str) -> Any:
        return self._get_entity_by_field(entity_id, entity_type, "id")

    def get_entities_by_ids(self, ids: list[str], entity_type: str) -> list[Any]:
        return self.get_items_by_ids(ids, entity_type)

    def get_items_by_keys(self, keys: list[str], path: str) -> list[Any]:
        return [item for item in self.get_entities_list(path) if item.get("key") in keys]

    def get_items_by_ids(self, ids: list[str], path: str) -> list[Any]:
        return [item for item in self.get_entities_list(path) if item.get("id") in ids]

    def get_sub_item(
        self,
        entity_type: str,
        entity_identity: str,
        sub_entity_type: str,
        sub_entity_identity: str,
        identity_field: str,
        sub_identity_field: str,
    ) -> Any:
        entity = self._get_entity_by_field(entity_identity, entity_type, identity_field)
        if not isinstance(entity, Mapping):
            return None
        for sub_entity in entity.get(sub_entity_type) or []:
            if str(sub_entity.get(sub_identity_field)) == str(sub_entity_identity):
                return sub_entity
        return None

    def filter_matched_records_with_rule(
        self,
        items: list[Mapping[str, Any]],
        data: Mapping[str, Any],
        identity_field: str = "key",
    ) -> list[Mapping[str, Any]]:
        matched = []
        for item in items:
            rules = item.get("rules")
            if rules and self._rule_manager.is_rule_matched(data, rules, str(item.get(identity_field))):
                matched.append(item)
        return matched

    def filter_matched_custom_segments(
        self,
        items: list[Mapping[str, Any]],
        visitor_id: str,
    ) -> list[Mapping[str, Any]]:
        store = self.get_data(visitor_id) or {}
        custom_segments = ((store.get("segments") or {}).get(SegmentsKeys.CUSTOM_SEGMENTS.value)) or []
        return [item for item in items if item.get("id") in custom_segments]

    def select_locations(
        self,
        visitor_id: str,
        items: list[Mapping[str, Any]],
        *,
        location_properties: Mapping[str, Any],
        identity_field: str = "key",
    ) -> list[Mapping[str, Any]]:
        del visitor_id, identity_field
        return self.filter_matched_records_with_rule(items, location_properties)

    def match_rules_by_field(
        self,
        visitor_id: str,
        identity: str,
        identity_field: str = "key",
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        attributes = attributes or {}
        visitor_properties = attributes.get("visitorProperties")
        location_properties = attributes.get("locationProperties")
        ignore_location_properties = attributes.get("ignoreLocationProperties", False)
        environment = attributes.get("environment", self._environment)

        experience = self._get_entity_by_field(identity, "experiences", identity_field)
        if not isinstance(experience, Mapping):
            return None

        archived = self.get_entities_list("archived_experiences")
        if str(experience.get("id")) in {str(item) for item in archived}:
            return None

        if experience.get("environment") and experience.get("environment") != environment:
            return None

        location_matched = bool(ignore_location_properties)
        if not location_matched:
            if location_properties:
                if experience.get("locations"):
                    locations = self.get_items_by_ids(experience["locations"], "locations")
                    location_matched = bool(
                        self.select_locations(
                            visitor_id,
                            locations,
                            location_properties=location_properties,
                            identity_field=identity_field,
                        )
                    )
                elif experience.get("site_area"):
                    location_matched = bool(
                        self._rule_manager.is_rule_matched(
                            location_properties, experience["site_area"], "SiteArea"
                        )
                    )
                else:
                    location_matched = True
            else:
                location_matched = not bool(experience.get("locations") or experience.get("site_area"))
        if not location_matched:
            return None

        store = self.get_data(visitor_id) or {}
        existing_bucketing = store.get("bucketing") or {}
        is_bucketed = str(experience.get("id")) in existing_bucketing

        audiences = self.get_items_by_ids(experience.get("audiences") or [], "audiences")
        if visitor_properties:
            audiences_to_check = [
                audience
                for audience in audiences
                if not (is_bucketed and audience.get("type") == "permanent")
            ]
            if audiences_to_check:
                matched_audiences = self.filter_matched_records_with_rule(
                    audiences_to_check,
                    visitor_properties,
                    identity_field,
                )
                matching_option = (
                    ((experience.get("settings") or {}).get("matching_options") or {}).get("audiences")
                    or "any"
                )
                audiences_matched = (
                    len(matched_audiences) == len(audiences_to_check)
                    if matching_option == "all"
                    else bool(matched_audiences)
                )
            else:
                audiences_matched = True
        else:
            audiences_matched = not audiences

        segments = self.get_items_by_ids(experience.get("audiences") or [], "segments")
        segments_matched = True
        if segments:
            segments_matched = bool(self.filter_matched_custom_segments(segments, visitor_id))

        variations = experience.get("variations") or []
        if audiences_matched and segments_matched and variations:
            return experience
        return None

    def _retrieve_variation(self, experience_id: str, variation_id: str) -> Any:
        return self.get_sub_item(
            "experiences",
            experience_id,
            "variations",
            variation_id,
            "id",
            "id",
        )

    def _retrieve_bucketing(
        self,
        visitor_id: str,
        visitor_properties: Mapping[str, Any] | None,
        update_visitor_properties: bool,
        experience: Mapping[str, Any],
        force_variation_id: str | None = None,
        enable_tracking: bool = True,
    ) -> Any:
        variation = None
        variation_id = None
        bucketing_allocation = None
        if force_variation_id:
            variation = self._retrieve_variation(str(experience.get("id")), str(force_variation_id))
            if variation:
                variation_id = force_variation_id

        store = self.get_data(visitor_id) or {}
        stored_variation_id = ((store.get("bucketing") or {}).get(str(experience.get("id"))))
        if (
            stored_variation_id
            and (variation_id is None or str(variation_id) == str(stored_variation_id))
        ):
            variation = self._retrieve_variation(str(experience.get("id")), str(stored_variation_id))
            if variation:
                variation_id = stored_variation_id

        if variation_id is None:
            buckets: dict[str, float] = {}
            for item in experience.get("variations") or []:
                if not isinstance(item, Mapping) or not item.get("id"):
                    continue
                if item.get("status") and item.get("status") != "running":
                    continue
                traffic = item.get("traffic_allocation")
                if traffic is None:
                    traffic = 100.0
                if traffic <= 0:
                    continue
                buckets[str(item["id"])] = float(traffic)
            bucketing = self._bucketing_manager.get_bucket_for_visitor(
                buckets,
                visitor_id,
                None
                if ((self._config.get("bucketing") or {}).get("excludeExperienceIdHash"))
                else {"experienceId": str(experience.get("id"))},
            )
            if not bucketing:
                return BucketingError.VARIAION_NOT_DECIDED
            variation_id = bucketing.variation_id
            bucketing_allocation = bucketing.bucketing_allocation
            if update_visitor_properties and visitor_properties:
                self.put_data(
                    visitor_id,
                    {
                        "bucketing": {str(experience.get("id")): variation_id},
                        "segments": dict(visitor_properties),
                    },
                )
            else:
                self.put_data(
                    visitor_id,
                    {"bucketing": {str(experience.get("id")): variation_id}},
                )
            if enable_tracking and self._api_manager:
                self._api_manager.enqueue(
                    visitor_id,
                    {
                        "eventType": "bucketing",
                        "data": {
                            "experienceId": str(experience.get("id")),
                            "variationId": str(variation_id),
                        },
                    },
                    (self.get_data(visitor_id) or {}).get("segments"),
                )
            variation = self._retrieve_variation(str(experience.get("id")), str(variation_id))

        if not variation:
            return None
        return {
            "experienceId": experience.get("id"),
            "experienceName": experience.get("name"),
            "experienceKey": experience.get("key"),
            "bucketingAllocation": bucketing_allocation,
            **variation,
        }

    def _get_bucketing_by_field(
        self,
        visitor_id: str,
        identity: str,
        identity_field: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        attributes = attributes or {}
        experience = self.match_rules_by_field(visitor_id, identity, identity_field, attributes)
        if not experience:
            return None
        if isinstance(experience, RuleError):
            return experience
        return self._retrieve_bucketing(
            visitor_id,
            attributes.get("visitorProperties"),
            bool(attributes.get("updateVisitorProperties")),
            experience,
            attributes.get("forceVariationId"),
            bool(attributes.get("enableTracking", True)),
        )

    def get_bucketing(
        self,
        visitor_id: str,
        key: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._get_bucketing_by_field(visitor_id, key, "key", attributes)

    def get_bucketing_by_id(
        self,
        visitor_id: str,
        entity_id: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._get_bucketing_by_field(visitor_id, entity_id, "id", attributes)

    def convert(
        self,
        visitor_id: str,
        goal_id: str,
        goal_rule: Mapping[str, Any] | None = None,
        goal_data: list[Mapping[str, Any]] | None = None,
        segments: Mapping[str, Any] | None = None,
        conversion_setting: Mapping[str, Any] | None = None,
    ) -> RuleError | bool | None:
        goal = self.get_entity(goal_id, "goals") or self.get_entity_by_id(goal_id, "goals")
        if not goal or not goal.get("id"):
            return None

        if goal_rule:
            goal_rules = goal.get("rules")
            if not goal_rules:
                return None
            rule_matched = self._rule_manager.is_rule_matched(
                goal_rule,
                goal_rules,
                f"ConfigGoal #{goal_id}",
            )
            if isinstance(rule_matched, RuleError):
                return rule_matched
            if not rule_matched:
                return None

        store_data = self.get_data(visitor_id) or {}
        bucketing_data = store_data.get("bucketing")
        goals = dict(store_data.get("goals") or {})
        already_triggered = bool(goals.get(str(goal_id)))
        force_multiple = bool(
            (conversion_setting or {}).get("force_multiple_transactions")
            or (conversion_setting or {}).get("forceMultipleTransactions")
        )
        if already_triggered and not force_multiple:
            return None

        self.put_data(visitor_id, {"goals": {str(goal_id): True}})

        def enqueue_conversion(payload: dict[str, Any]) -> None:
            if not self._api_manager:
                return
            if bucketing_data:
                payload["bucketingData"] = bucketing_data
            self._api_manager.enqueue(
                visitor_id,
                {"eventType": "conversion", "data": payload},
                segments,
            )

        if not already_triggered:
            enqueue_conversion({"goalId": str(goal.get("id"))})

        if goal_data and (not already_triggered or force_multiple):
            enqueue_conversion({"goalId": str(goal.get("id")), "goalData": goal_data})

        return True
