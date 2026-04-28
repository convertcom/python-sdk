"""Deterministic visitor bucketing helpers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


DEFAULT_HASH_SEED = 9999
DEFAULT_MAX_TRAFFIC = 10000
DEFAULT_MAX_HASH = 4294967296


def _rotl32(value: int, shift: int) -> int:
    return ((value << shift) & 0xFFFFFFFF) | (value >> (32 - shift))


def murmurhash3_32(value: str, seed: int = DEFAULT_HASH_SEED) -> int:
    """Return the unsigned MurmurHash3 32-bit value for a string."""

    data = bytearray(value.encode("utf-8"))
    length = len(data)
    nblocks = length // 4
    h1 = seed & 0xFFFFFFFF

    c1 = 0xCC9E2D51
    c2 = 0x1B873593

    for block_start in range(0, nblocks * 4, 4):
        k1 = (
            data[block_start]
            | (data[block_start + 1] << 8)
            | (data[block_start + 2] << 16)
            | (data[block_start + 3] << 24)
        )
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = _rotl32(k1, 15)
        k1 = (k1 * c2) & 0xFFFFFFFF

        h1 ^= k1
        h1 = _rotl32(h1, 13)
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    tail = data[nblocks * 4 :]
    k1 = 0

    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = _rotl32(k1, 15)
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


def get_bucket_value(
    visitor_id: str,
    experience_id: str,
    *,
    seed: int = DEFAULT_HASH_SEED,
    max_traffic: int = DEFAULT_MAX_TRAFFIC,
) -> int:
    """Return a stable traffic bucket value for a visitor/experience pair."""

    hash_value = murmurhash3_32(f"{experience_id}{visitor_id}", seed)
    bucket_value = (hash_value / DEFAULT_MAX_HASH) * max_traffic
    return int(bucket_value)


def select_variation(
    variations: Sequence[Mapping[str, Any]],
    *,
    visitor_id: str,
    experience_id: str,
    bucketing_config: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], int] | None:
    """Select the bucketed variation for a visitor from ordered allocations."""

    seed = int(bucketing_config.get("hash_seed", DEFAULT_HASH_SEED)) if bucketing_config else DEFAULT_HASH_SEED
    max_traffic = (
        int(bucketing_config.get("max_traffic", DEFAULT_MAX_TRAFFIC))
        if bucketing_config
        else DEFAULT_MAX_TRAFFIC
    )
    bucket_value = get_bucket_value(
        visitor_id,
        experience_id,
        seed=seed,
        max_traffic=max_traffic,
    )

    cumulative = 0.0
    for variation in variations:
        # JS treats only ``status === 'running'`` as eligible
        # (``VariationStatuses`` enum is ``'stopped' | 'running'``). When
        # ``status`` is absent, JS defaults to running. Mirror that
        # exactly — accepting "active" admitted variations JS would skip.
        status = variation.get("status")
        if status not in (None, "", "running"):
            continue

        # JS ``data-manager.ts`` treats a missing ``traffic_allocation``
        # as 100% (``allocation ?? 100``). Python previously defaulted
        # to 0, which silently excluded any variation whose allocation
        # was unset. Use a sentinel to distinguish missing-vs-zero.
        raw_allocation = variation.get("traffic_allocation")
        if raw_allocation is None:
            allocation = 100.0
        else:
            try:
                allocation = float(raw_allocation)
            except (TypeError, ValueError):
                # JS ``Number()`` coerces non-numeric to NaN and the
                # subsequent comparisons return false; we mirror with
                # 0 so the variation is effectively skipped.
                allocation = 0.0
        cumulative += allocation * 100
        if bucket_value < cumulative:
            return variation, bucket_value

    return None
