"""Cross-SDK value-exact parity tests for feature resolution (Story 3.5 / NFR20).

Each vector in ``fixtures/feature_vectors.json`` pairs a config + visitor inputs
with the JS reference ``expected`` resolution (status + cast variables, or a
``null`` -> ``None`` miss), machine-derived by ``scripts/generate_parity_fixtures.py``
from the JS feature-resolution path (bucketing + ``fullStackFeature`` change
casting). Each vector is fed through the Python SDK's REAL surface
(Story 1.5/1.6 ``evaluation/features.resolve_feature`` over a real
``ConfigSnapshot``) — the byte-identical Python MurmurHash3 makes the bucketed
variation choice match the JS reference.

Runs OFFLINE and JS-runtime-free: loads only the checked-in JSON (via the
``feature_vectors`` conftest loader) and exercises the pure-Python SDK. On
failure the assertion names the fixture, the entry id, expected-JS, actual-Python.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import FeatureStatus
from convert_sdk.evaluation.features import resolve_feature

_FIXTURE = "feature_vectors.json"
_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / _FIXTURE).read_text(encoding="utf-8")
)["vectors"]


def _result_to_comparable(result):
    """Project a Python ``FeatureResult`` into the JS reference's plain shape."""
    if result is None:
        return None
    status = result.status
    status_value = status.value if isinstance(status, FeatureStatus) else str(status)
    return {
        "feature_key": result.feature_key,
        "feature_id": str(result.feature_id),
        "status": str(status_value).lower(),
        "variables": dict(result.variables),
        "experience_key": result.experience_key,
        "variation_key": result.variation_key,
    }


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["id"] for v in _VECTORS])
def test_feature_resolution_matches_js_reference(vector, feature_vectors):
    """Python ``resolve_feature`` must equal the JS feature-resolution reference."""
    assert isinstance(feature_vectors, list) and feature_vectors

    snapshot = load_snapshot(vector["config"])
    result = resolve_feature(
        vector["feature_key"],
        snapshot,
        visitor_id=vector["visitor_id"],
    )
    actual = _result_to_comparable(result)
    assert actual == vector["expected"], (
        f"feature parity divergence in {_FIXTURE} [{vector['id']}]: "
        f"feature={vector['feature_key']!r} visitor={vector['visitor_id']!r} -> "
        f"python={actual!r} != js={vector['expected']!r}"
    )
