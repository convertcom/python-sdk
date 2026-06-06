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
