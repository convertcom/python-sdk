from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.utils.object_utils import object_deep_merge

DEFAULT_CONFIG: dict[str, Any] = {
    "api": {"endpoint": {"config": "", "track": ""}},
    "environment": "staging",
    "bucketing": {"max_traffic": 10000, "hash_seed": 9999},
    "cache": {"max_entries": 10000},
    "data": {},
    "dataStore": None,
    "dataRefreshInterval": 300000,
    "events": {"batch_size": 10, "release_interval": 1000},
    "logger": {"logLevel": "debug", "customLoggers": []},
    "rules": {"keys_case_sensitive": True, "comparisonProcessor": None},
    "network": {
        "tracking": True,
        "cacheLevel": "default",
        "source": "python-sdk",
        "requestTimeout": 10.0,
        "configRetries": 1,
        "trackRetries": 0,
        "retryBackoff": 0.0,
    },
    "sdkKey": "",
    "sdkKeySecret": "",
}


def build_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return object_deep_merge(DEFAULT_CONFIG, dict(config or {}))
