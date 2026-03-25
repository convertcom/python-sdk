from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping, TypedDict


ComparisonProcessor = Mapping[str, Callable[..., bool]]


@dataclass(frozen=True)
class BucketingHashOptions:
    seed: int = 9999
    experience_id: str = ""
    redistribute: int = 0


@dataclass(frozen=True)
class BucketingAllocationType:
    variation_id: str
    bucketing_allocation: int


class RuleMatching(TypedDict):
    match_type: str
    negated: bool


class RuleElement(TypedDict, total=False):
    key: str
    rule_type: str
    matching: RuleMatching
    value: Any


RuleObject = MutableMapping[str, Any]
