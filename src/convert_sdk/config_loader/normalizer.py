"""Boundary normalization helpers for config ingestion."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ..domain.config_snapshot import ConfigSnapshot


def normalize_config_data(config_data: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized: Dict[str, Any] = dict(config_data)
    normalized.setdefault("experiences", ())
    normalized.setdefault("features", ())
    normalized.setdefault("goals", ())
    normalized.setdefault("audiences", ())
    normalized.setdefault("segments", ())
    normalized.setdefault("archived_experiences", ())
    return normalized


def build_snapshot(config_data: Mapping[str, Any]) -> ConfigSnapshot:
    return ConfigSnapshot.from_config_data(normalize_config_data(config_data))
