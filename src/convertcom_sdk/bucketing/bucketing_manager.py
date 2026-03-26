from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from convertcom_sdk.utils.string_utils import generate_hash


DEFAULT_HASH_SEED = 9999
DEFAULT_MAX_TRAFFIC = 10000
DEFAULT_MAX_HASH = 4294967296


@dataclass(frozen=True)
class BucketingAllocation:
    variation_id: str
    bucketing_allocation: int


class BucketingManager:
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        config = config or {}
        bucketing = config.get("bucketing") or {}
        self._max_traffic = int(bucketing.get("max_traffic") or DEFAULT_MAX_TRAFFIC)
        self._hash_seed = int(bucketing.get("hash_seed") or DEFAULT_HASH_SEED)

    def select_bucket(
        self,
        buckets: Mapping[str, int],
        value: int,
        redistribute: int = 0,
    ) -> str | None:
        selected: str | None = None
        previous = 0
        for variation_id in buckets.keys():
            previous += buckets[variation_id] * 100 + redistribute
            if value < previous:
                selected = variation_id
                break
        return selected

    def get_value_visitor_based(
        self,
        visitor_id: str,
        options: Mapping[str, Any] | None = None,
    ) -> int:
        options = options or {}
        seed = int(options.get("seed", self._hash_seed))
        experience_id = str(options.get("experienceId", ""))
        hash_value = generate_hash(experience_id + str(visitor_id), seed)
        value = (hash_value / DEFAULT_MAX_HASH) * self._max_traffic
        return int(str(value).split(".", 1)[0])

    def get_bucket_for_visitor(
        self,
        buckets: Mapping[str, int],
        visitor_id: str,
        options: Mapping[str, Any] | None = None,
    ) -> BucketingAllocation | None:
        options = options or {}
        value = self.get_value_visitor_based(visitor_id, options)
        selected_bucket = self.select_bucket(
            buckets,
            value,
            int(options.get("redistribute", 0)),
        )
        if not selected_bucket:
            return None
        return BucketingAllocation(
            variation_id=selected_bucket,
            bucketing_allocation=value,
        )
