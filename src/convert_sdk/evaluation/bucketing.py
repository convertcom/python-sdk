"""Deterministic visitor bucketing for local experience evaluation (Story 1.4).

This module ships a **pure-Python** MurmurHash3-32 implementation that produces
byte-exact identical output to the JavaScript SDK's bucketing hash for the same
inputs. No third-party hashing library is taken on as a runtime dependency
(``httpx`` remains the SDK's only runtime dependency) — see
``qs-04-murmurhash3-wrapper.md`` and ``architecture.md`` §MurmurHash3 Bucketing
Parity Strategy (ADR decision #10).

Parity contract
---------------
The JS SDK imports the npm ``murmurhash`` package and calls ``Murmurhash.v3``
(``../javascript-sdk/packages/utils/src/string-utils.ts`` ``generateHash``,
default seed ``9999``). That implementation processes the input via
``charCodeAt(i) & 0xff`` over **UTF-16 code units** (not UTF-8 bytes) and mixes
in ``key.length`` measured in code units. :func:`murmurhash3_32` replicates this
exactly so the output is byte-exact against the JS reference across the full
golden-vector suite in ``tests/parity/fixtures/bucketing_vectors.json``.

Output is an **unsigned** 32-bit integer in ``[0, 2**32)`` — matching the npm
``v3`` output the JS bucketing manager divides by ``DEFAULT_MAX_HASH``
(``4294967296``).
"""

from __future__ import annotations

from typing import Mapping, Optional

# Frozen bucketing constants — match the JS SDK's BucketingManager defaults
# (../javascript-sdk/packages/bucketing/src/bucketing-manager.ts).
DEFAULT_HASH_SEED = 9999
DEFAULT_MAX_TRAFFIC = 10000
DEFAULT_MAX_HASH = 4294967296  # 2 ** 32

_UINT32_MASK = 0xFFFFFFFF
_C1 = 0xCC9E2D51
_C2 = 0x1B873593


def _utf16_code_units(value: str) -> list[int]:
    """Return the UTF-16 code units of ``value`` as a list of ints.

    JavaScript strings are sequences of UTF-16 code units, and the npm
    ``murmurhash`` ``v3`` implementation reads them via ``charCodeAt``. Python
    ``str`` indexing yields Unicode code points, so characters outside the BMP
    must be split into surrogate pairs to match JS ``charCodeAt`` semantics.
    """
    units: list[int] = []
    for char in value:
        code_point = ord(char)
        if code_point > 0xFFFF:
            # Encode as a UTF-16 surrogate pair (matches JS string storage).
            code_point -= 0x10000
            units.append(0xD800 + (code_point >> 10))
            units.append(0xDC00 + (code_point & 0x3FF))
        else:
            units.append(code_point)
    return units


def _rotl32(value: int, shift: int) -> int:
    """Rotate a 32-bit unsigned integer left by ``shift`` bits."""
    value &= _UINT32_MASK
    return ((value << shift) | (value >> (32 - shift))) & _UINT32_MASK


def murmurhash3_32(value: str, seed: int = DEFAULT_HASH_SEED) -> int:
    """Compute the MurmurHash3-32 of ``value`` as an unsigned 32-bit integer.

    Byte-exact with the JavaScript SDK's ``Murmurhash.v3`` (npm ``murmurhash``)
    for the same inputs. The default ``seed`` is ``9999`` — the frozen Convert
    bucketing seed shared across the JS, PHP, and Python SDKs.

    Args:
        value: The string to hash. Non-``str`` callers must coerce first.
        seed: The hash seed. Defaults to ``9999``.

    Returns:
        An unsigned 32-bit integer in ``[0, 2**32)``.
    """
    units = _utf16_code_units(value)
    length = len(units)
    remainder = length & 3
    bytes_count = length - remainder

    h1 = seed & _UINT32_MASK
    i = 0

    while i < bytes_count:
        k1 = (
            (units[i] & 0xFF)
            | ((units[i + 1] & 0xFF) << 8)
            | ((units[i + 2] & 0xFF) << 16)
            | ((units[i + 3] & 0xFF) << 24)
        ) & _UINT32_MASK
        i += 4

        k1 = (k1 * _C1) & _UINT32_MASK
        k1 = _rotl32(k1, 15)
        k1 = (k1 * _C2) & _UINT32_MASK

        h1 ^= k1
        h1 = _rotl32(h1, 13)
        h1 = (h1 * 5 + 0xE6546B64) & _UINT32_MASK

    k1 = 0
    if remainder == 3:
        k1 ^= (units[i + 2] & 0xFF) << 16
    if remainder >= 2:
        k1 ^= (units[i + 1] & 0xFF) << 8
    if remainder >= 1:
        k1 ^= units[i] & 0xFF
        k1 = (k1 * _C1) & _UINT32_MASK
        k1 = _rotl32(k1, 15)
        k1 = (k1 * _C2) & _UINT32_MASK
        h1 ^= k1

    # Finalization — mix in the code-unit length, then the avalanche.
    h1 ^= length
    h1 &= _UINT32_MASK
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & _UINT32_MASK
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & _UINT32_MASK
    h1 ^= h1 >> 16

    return h1 & _UINT32_MASK


def get_bucket_value_for_visitor(
    visitor_id: str,
    *,
    experience_id: str = "",
    seed: int = DEFAULT_HASH_SEED,
    max_traffic: int = DEFAULT_MAX_TRAFFIC,
    max_hash: int = DEFAULT_MAX_HASH,
) -> int:
    """Compute a deterministic bucket value for a visitor in ``[0, max_traffic)``.

    Mirrors the JS SDK's ``getValueVisitorBased``: hashes
    ``f"{experience_id}{visitor_id}"`` and maps the unsigned 32-bit hash into the
    traffic range via ``int((hash / max_hash) * max_traffic)``. The same visitor
    and experience always produce the same value against the same snapshot.
    """
    composite = f"{experience_id}{visitor_id}"
    hash_value = murmurhash3_32(composite, seed)
    return int((hash_value / max_hash) * max_traffic)


def select_bucket(
    buckets: Mapping[str, float],
    value: int,
    redistribute: int = 0,
) -> Optional[str]:
    """Select a bucket id for ``value`` from percentage-weighted ``buckets``.

    Mirrors the JS SDK's ``selectBucket``: walks the buckets in iteration order,
    accumulating ``pct * 100 + redistribute`` and returning the first bucket id
    whose cumulative threshold exceeds ``value``. Returns ``None`` when no bucket
    matches (e.g. empty buckets, or ``value`` beyond the cumulative range) — a
    normal no-result outcome, never an exception.
    """
    cumulative = 0.0
    for bucket_id, percentage in buckets.items():
        cumulative += percentage * 100 + redistribute
        if value < cumulative:
            return bucket_id
    return None
