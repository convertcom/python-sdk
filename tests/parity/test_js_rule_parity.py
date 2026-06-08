"""Cross-SDK byte/value-exact parity tests for rule evaluation (Story 3.5 / NFR20).

Each vector in ``fixtures/rule_vectors.json`` pairs a ``data`` mapping + a nested
``OR / AND / OR_WHEN`` rule set with the JS reference ``expected`` boolean,
machine-derived from the JS ``RuleManager`` + ``Comparisons`` by
``scripts/generate_parity_fixtures.py``. Every vector is fed through the Python
SDK's REAL rule-evaluation surface (Story 1.4 ``evaluation/rules.is_rule_matched``)
— the test never re-implements rule logic.

Runs OFFLINE and JS-runtime-free: it loads only the checked-in JSON (via the
``rule_vectors`` conftest loader) and exercises the pure-Python SDK. On failure
the assertion names the fixture file, the entry id, the expected JS value, and
the actual Python value (AC #3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convert_sdk.evaluation.rules import is_rule_matched

_FIXTURE = "rule_vectors.json"
_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / _FIXTURE).read_text(encoding="utf-8")
)["vectors"]


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["id"] for v in _VECTORS])
def test_rule_evaluation_matches_js_reference(vector, rule_vectors):
    """Python ``is_rule_matched`` must equal the JS ``RuleManager`` reference."""
    # The conftest loader is consumed so no test inlines fixture data; the
    # module-level _VECTORS only drives parametrize ids/cases.
    assert isinstance(rule_vectors, list) and rule_vectors

    result = is_rule_matched(vector["data"], vector["rule"])
    assert result == vector["expected"], (
        f"rule parity divergence in {_FIXTURE} [{vector['id']}]: "
        f"data={vector['data']!r} -> python={result!r} != js={vector['expected']!r}"
    )
