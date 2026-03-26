from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.utils import DEFAULT_COMPARISON_PROCESSOR, camel_case
from convertcom_sdk.utils.object_utils import object_not_empty


DEFAULT_KEYS_CASE_SENSITIVE = True
DEFAULT_NEGATION = "!"


class RuleManager:
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        config = config or {}
        rules_config = config.get("rules") or {}
        self._comparison_processor = (
            rules_config.get("comparisonProcessor") or DEFAULT_COMPARISON_PROCESSOR
        )
        self._negation = str(rules_config.get("negation") or DEFAULT_NEGATION)
        self._keys_case_sensitive = rules_config.get(
            "keys_case_sensitive", DEFAULT_KEYS_CASE_SENSITIVE
        )

    @property
    def comparison_processor(self) -> Mapping[str, Any]:
        return self._comparison_processor

    @comparison_processor.setter
    def comparison_processor(self, comparison_processor: Mapping[str, Any]) -> None:
        self._comparison_processor = comparison_processor

    def get_comparison_processor_methods(self) -> list[str]:
        return [
            name
            for name, value in self._comparison_processor.items()
            if callable(value)
        ]

    def is_valid_rule(self, rule: Mapping[str, Any]) -> bool:
        matching = rule.get("matching")
        return (
            isinstance(rule, Mapping)
            and isinstance(matching, Mapping)
            and isinstance(matching.get("match_type"), str)
            and isinstance(matching.get("negated"), bool)
            and "value" in rule
        )

    def is_rule_matched(
        self, data: Any, rule_set: Mapping[str, Any], log_entry: str | None = None
    ) -> bool:
        del log_entry
        match = False
        if isinstance(rule_set, Mapping) and isinstance(rule_set.get("OR"), list) and rule_set["OR"]:
            for item in rule_set["OR"]:
                match = self._process_and(data, item)
                if match is True:
                    return True
            return bool(match)
        return False

    def _process_and(self, data: Any, rules_subset: Any) -> bool:
        if isinstance(rules_subset, Mapping) and isinstance(rules_subset.get("AND"), list) and rules_subset["AND"]:
            for item in rules_subset["AND"]:
                match = self._process_or_when(data, item)
                if match is not True:
                    return match
            return True
        return False

    def _process_or_when(self, data: Any, rules_subset: Any) -> bool:
        if isinstance(rules_subset, Mapping) and isinstance(rules_subset.get("OR_WHEN"), list) and rules_subset["OR_WHEN"]:
            match = False
            for item in rules_subset["OR_WHEN"]:
                match = self._process_rule_item(data, item)
                if match is True:
                    return True
            return bool(match)
        return False

    def _process_rule_item(self, data: Any, rule: Any) -> bool:
        if not isinstance(rule, Mapping) or not self.is_valid_rule(rule):
            return False

        negation = bool(rule["matching"].get("negated", False))
        matching = rule["matching"]["match_type"]
        if matching not in self.get_comparison_processor_methods():
            return False

        if not isinstance(data, Mapping):
            return False

        if self._is_using_custom_interface(data):
            rule_type = rule.get("rule_type")
            if rule_type:
                rule_method = camel_case(f"get {rule_type.replace('_', ' ')}")
                for method_name in dir(data):
                    if method_name == "__class__":
                        continue
                    method = getattr(data, method_name, None)
                    if not callable(method):
                        continue
                    mapper = getattr(data, "mapper", None)
                    mapped_name = mapper(method_name) if callable(mapper) else None
                    if method_name == rule_method or mapped_name == rule_method:
                        data_value = method(rule)
                        if rule_type == "js_condition":
                            return bool(data_value)
                        return bool(
                            self._comparison_processor[matching](
                                data_value,
                                rule["value"],
                                negation,
                            )
                        )
            return False

        if object_not_empty(data):
            for key, value in data.items():
                left_key = key if self._keys_case_sensitive else str(key).lower()
                rule_key = rule["key"] if self._keys_case_sensitive else str(rule["key"]).lower()
                if left_key == rule_key:
                    return bool(
                        self._comparison_processor[matching](
                            value,
                            rule["value"],
                            negation,
                        )
                    )
        return False

    def _is_using_custom_interface(self, data: Any) -> bool:
        return object_not_empty(data) and data.get("name") == "RuleData"
