"""Cross-SDK byte-exact parity tests for MurmurHash3-32 bucketing (qs-04 / NFR20).

Byte-exact parity against JS-derived golden vectors is the success criterion —
not "deterministic across runs" (a buggy hash is also deterministic). Vectors
in ``fixtures/bucketing_vectors.json`` are machine-derived from the npm
``murmurhash`` ``v3`` algorithm the Convert JS SDK imports
(``packages/utils/src/string-utils.ts`` ``generateHash``, default seed 9999).
"""

import json
from pathlib import Path

import pytest

from convert_sdk.evaluation.bucketing import murmurhash3_32

_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "bucketing_vectors.json").read_text(
        encoding="utf-8"
    )
)["vectors"]


@pytest.mark.parametrize(
    "vector",
    _VECTORS,
    ids=[f"seed{v['seed']}:{v['value']!r}" for v in _VECTORS],
)
def test_murmurhash3_32_matches_js_reference(vector):
    """Every Python hash output must be byte-exact with the JS reference."""
    result = murmurhash3_32(vector["value"], vector["seed"])
    assert result == vector["expected"], (
        f"parity divergence for value={vector['value']!r} seed={vector['seed']}: "
        f"python={result} != js={vector['expected']}"
    )


def test_default_seed_is_9999():
    """A call without an explicit seed must use the frozen default 9999."""
    assert murmurhash3_32("test_visitor") == murmurhash3_32("test_visitor", 9999)


def test_output_is_unsigned_32_bit():
    """Output is always an unsigned 32-bit integer in [0, 2**32)."""
    for vector in _VECTORS:
        result = murmurhash3_32(vector["value"], vector["seed"])
        assert 0 <= result < 2**32
