"""Cross-SDK byte-exact parity tests for the anchored bucketing layout
(qs-01-anchored-bucketing-layout.md, bucketing contract v12).

The ``experience.version > 11`` gate and the anchored selector live in
``convert_sdk.evaluation.experiences`` / ``convert_sdk.evaluation.bucketing``.
The full fixture (59/59 vectors, versions ``{11, 12}``) must pass -- this is
AC7. The ``version: 11`` vectors exercise the untouched packed path and must
stay green (AC6 packed regression lock).

Fixture shape differs from the sibling ``bucketing_vectors.json``: the root of
``fixtures/anchored_bucketing_vectors.json`` is a BARE JSON LIST (no
``{"vectors": [...]}`` wrapper) -- see qs-01-anchored-bucketing-layout.md
"Golden-vector fixture" and PY-1 (the commit that imported this fixture).

Each vector is fed through the SAME public seam the SDK uses in production --
``convert_sdk.evaluation.experiences.select_experience`` -- over a real
``ConfigSnapshot`` built from ``{experienceId, variations, version}``. Never a
hand-rolled reimplementation of the algorithm: the fixture's expected values
ARE the cross-SDK contract (machine-derived from the JS reference), so a
mismatch here is a bug in this port, not the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.evaluation.experiences import select_experience

_FIXTURE = "anchored_bucketing_vectors.json"
_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / _FIXTURE).read_text(encoding="utf-8")
)


def _snapshot_for_vector(vector: "dict[str, Any]") -> Any:
    """Build a minimal single-experience snapshot from a golden vector.

    Maps the fixture's ``{experienceId, variations, version}`` shape onto the
    experience config dict ``select_experience`` reads (Story 1.4 shape).
    ``version`` is copied through as-is (including when absent) so vectors
    exercise exactly the gate branch their ``description`` names.
    """
    experience: "dict[str, Any]" = {
        "id": vector["experienceId"],
        "key": vector["experienceId"],
        "variations": vector["variations"],
        "version": vector["version"],
    }
    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": [experience],
        }
    )


@pytest.mark.parametrize(
    "vector",
    _VECTORS,
    ids=[f"{i:02d}-{v['visitorId']}-v{v['version']}" for i, v in enumerate(_VECTORS)],
)
def test_anchored_bucketing_matches_js_reference(vector, anchored_bucketing_vectors):
    """AC1 / AC6 / AC7 -- the full golden fixture must resolve through
    ``select_experience`` exactly as the JS reference does.

    ``version <= 11`` vectors exercise the untouched packed path (AC6
    regression lock); ``version > 11`` vectors exercise the anchored path this
    fixture is the contract for (AC7). AC1's gate is exercised implicitly and
    exhaustively: 8 visitor/experience pairs in this fixture are asserted
    against BOTH a ``version: 11`` and a ``version: 12`` variations config with
    the IDENTICAL (and therefore identical hash-derived) bucket value, expecting
    DIFFERENT outcomes -- which only passes because ``version`` actually
    selects the layout.
    """
    assert isinstance(anchored_bucketing_vectors, list) and anchored_bucketing_vectors

    snapshot = _snapshot_for_vector(vector)
    result = select_experience(
        str(vector["experienceId"]), snapshot, visitor_id=vector["visitorId"]
    )
    actual = result.variation_id if result is not None else None
    assert actual == vector["expected"], (
        f"anchored-bucketing parity divergence in {_FIXTURE} "
        f"[{vector['description']}]: experience={vector['experienceId']!r} "
        f"visitor={vector['visitorId']!r} version={vector['version']!r} -> "
        f"python={actual!r} != js={vector['expected']!r}"
    )


def test_packed_only_v11_subset_is_already_green_today():
    """AC6 regression lock, isolated from the anchored assertions above: the
    ``version: 11`` subset exercises the packed path independently of the
    anchored path, so a future regression in the packed path is caught even
    if an anchored-path assertion above fails for unrelated reasons.
    """
    v11_vectors = [v for v in _VECTORS if v["version"] == 11]
    assert v11_vectors, "fixture must contain v11 (packed) vectors"
    for vector in v11_vectors:
        snapshot = _snapshot_for_vector(vector)
        result = select_experience(
            str(vector["experienceId"]), snapshot, visitor_id=vector["visitorId"]
        )
        actual = result.variation_id if result is not None else None
        assert actual == vector["expected"], (
            f"packed-regression divergence [{vector['description']}]: "
            f"python={actual!r} != js={vector['expected']!r}"
        )
