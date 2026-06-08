"""Pytest fixture loaders for cross-SDK parity golden vectors (qs-05).

Fixtures are checked-in JSON so CI never needs a JavaScript runtime at test
time. Long-term ownership of the regeneration workflow belongs to Story 3.5;
Story 1.4 ships the bucketing vectors it needs and the loader they consume.
"""

import json
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with (_FIXTURES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def bucketing_vectors() -> list:
    """Golden MurmurHash3-32 input/output vectors derived from the JS reference."""
    return _load("bucketing_vectors.json")["vectors"]


@pytest.fixture(scope="session")
def rule_vectors() -> list:
    """Golden rule-evaluation vectors derived from the JS ``RuleManager`` reference.

    Each entry pairs a ``data`` mapping + a ``rule`` set with the JS reference
    ``expected`` boolean, exercised through the Python ``is_rule_matched`` surface
    (Story 1.4 ``evaluation/rules.py``).
    """
    return _load("rule_vectors.json")["vectors"]


@pytest.fixture(scope="session")
def feature_vectors() -> list:
    """Golden feature-resolution vectors derived from the JS feature path.

    Each entry pairs a config + visitor inputs with the JS reference expected
    resolution (status + cast variables, or a ``None`` miss), exercised through
    the Python ``resolve_feature`` surface (Story 1.5/1.6 ``evaluation/features.py``).
    """
    return _load("feature_vectors.json")["vectors"]


@pytest.fixture(scope="session")
def state_vectors() -> list:
    """Golden Epic-3 state / entity-lookup + segment vectors from the JS reference.

    Each entry pairs a config + a lookup/segment operation with the JS reference
    expected result, mirroring the ``DataManager.getEntity``/``getEntityById``/
    ``getEntities`` and ``SegmentsManager`` surfaces. Encodes the Story-3.4
    ``null`` -> ``None``/empty no-match contract (NOT the FR50 typed reason).
    """
    return _load("state_vectors.json")["vectors"]
