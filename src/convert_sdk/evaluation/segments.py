"""Local segment helpers for visitor-scoped state and matching."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..domain.config_snapshot import ConfigSnapshot
from .rules import evaluate_rules


def evaluate_custom_segments(
    snapshot: ConfigSnapshot,
    *,
    segment_keys: Sequence[str],
    attributes: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return the matched segment keys for the provided segment candidates."""

    matched_segments: list[str] = []
    seen: set[str] = set()
    for segment_key in segment_keys:
        normalized_key = str(segment_key).strip()
        if not normalized_key or normalized_key in seen:
            continue
        seen.add(normalized_key)

        segment = snapshot.segments_by_key.get(normalized_key)
        if segment is None:
            continue
        if evaluate_rules(_as_mapping(segment.get("rules")), attributes):
            matched_segments.append(normalized_key)

    return tuple(matched_segments)


def normalize_default_segments(segment_keys: Sequence[str]) -> tuple[str, ...]:
    """Normalize default segment keys into a stable tuple."""

    if isinstance(segment_keys, (str, bytes, bytearray)):
        raise TypeError("segment_keys must be a sequence of strings")
    if not isinstance(segment_keys, Sequence):
        raise TypeError("segment_keys must be a sequence of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for segment_key in segment_keys:
        candidate = str(segment_key).strip()
        if not candidate or candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return tuple(normalized)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None
