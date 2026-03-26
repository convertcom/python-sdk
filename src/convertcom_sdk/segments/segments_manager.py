from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.data import DataManager
from convertcom_sdk.enums import SegmentsKeys
from convertcom_sdk.rules import RuleManager


class SegmentsManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        data_manager: DataManager,
        rule_manager: RuleManager,
    ) -> None:
        del config
        self._data_manager = data_manager
        self._rule_manager = rule_manager

    def get_segments(self, visitor_id: str) -> dict[str, Any] | None:
        store_data = self._data_manager.get_data(visitor_id) or {}
        filtered = self._data_manager.filter_report_segments(store_data.get("segments"))
        return filtered["segments"]

    def put_segments(self, visitor_id: str, segments: Mapping[str, Any]) -> None:
        filtered = self._data_manager.filter_report_segments(segments)
        report_segments = filtered["segments"]
        if report_segments:
            self._data_manager.put_data(visitor_id, {"segments": report_segments})

    def _set_custom_segments(
        self,
        visitor_id: str,
        segments: list[Mapping[str, Any]],
        segment_rule: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        store_data = self._data_manager.get_data(visitor_id) or {}
        current_segments = dict(store_data.get("segments") or {})
        custom_segments = list(current_segments.get(SegmentsKeys.CUSTOM_SEGMENTS.value) or [])

        matched_ids: list[str] = []
        for segment in segments:
            if not segment.get("id"):
                continue
            if segment_rule and not self._rule_manager.is_rule_matched(
                segment_rule, segment.get("rules") or {}, f"ConfigSegment #{segment.get('id')}"
            ):
                continue
            segment_id = str(segment["id"])
            if segment_id not in custom_segments:
                matched_ids.append(segment_id)

        if matched_ids:
            segments_data = {
                **current_segments,
                SegmentsKeys.CUSTOM_SEGMENTS.value: [*custom_segments, *matched_ids],
            }
            self.put_segments(visitor_id, segments_data)
            return segments_data
        return current_segments or None

    def select_custom_segments(
        self,
        visitor_id: str,
        segment_keys: list[str],
        segment_rule: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        segments = self._data_manager.get_entities(segment_keys, "segments")
        return self._set_custom_segments(visitor_id, segments, segment_rule)

    def select_custom_segments_by_ids(
        self,
        visitor_id: str,
        segment_ids: list[str],
        segment_rule: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        segments = self._data_manager.get_entities_by_ids(segment_ids, "segments")
        return self._set_custom_segments(visitor_id, segments, segment_rule)
