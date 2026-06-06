"""Unit tests for typed results and snapshot-backed experience selection.

Story 1.4, SDK-3. Covers the typed :class:`ExperienceResult` model and the
``evaluation.experiences.select_experience`` selector: qualified visitors get a
typed result, normal misses return ``None``, selection is deterministic for the
same visitor + snapshot, results are typed objects (never raw config dicts), and
selection never mutates the snapshot.
"""

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation.experiences import select_experience


def _snapshot(experiences, audiences=()):
    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": list(experiences),
            "audiences": list(audiences),
        }
    )


def _running_experience():
    return {
        "id": "e1",
        "key": "exp-one",
        "variations": [
            {"id": "v1", "key": "control", "traffic_allocation": 50.0},
            {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
        ],
    }


# --- typed result model -------------------------------------------------------


def test_result_is_typed_not_raw_dict():
    snap = _snapshot([_running_experience()])
    result = select_experience("exp-one", snap, visitor_id="visitor-1")
    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "exp-one"
    assert result.experience_id == "e1"
    assert result.variation_id in {"v1", "v2"}
    assert result.variation_key in {"control", "treatment"}


def test_result_variation_payload_is_read_only_mapping():
    snap = _snapshot([_running_experience()])
    result = select_experience("exp-one", snap, visitor_id="visitor-1")
    # Payload exposes the variation but must not be a mutable alias.
    import pytest

    with pytest.raises(Exception):
        result.variation["injected"] = "x"  # type: ignore[index]


# --- qualified selection ------------------------------------------------------


def test_qualified_visitor_gets_variation():
    snap = _snapshot([_running_experience()])
    result = select_experience("exp-one", snap, visitor_id="visitor-1")
    assert result is not None
    assert result.variation_id in {"v1", "v2"}


def test_selection_is_deterministic():
    snap = _snapshot([_running_experience()])
    a = select_experience("exp-one", snap, visitor_id="visitor-42")
    b = select_experience("exp-one", snap, visitor_id="visitor-42")
    assert a is not None and b is not None
    assert a.variation_id == b.variation_id


# --- normal-miss outcomes (None, never exceptions) ----------------------------


def test_missing_experience_returns_none():
    snap = _snapshot([_running_experience()])
    assert select_experience("nope", snap, visitor_id="visitor-1") is None


def test_unqualified_visitor_returns_none():
    aud = {
        "id": "a1",
        "key": "aud",
        "rules": {
            "OR": [
                {"AND": [{"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "country", "value": "US"}]}]}
            ]
        },
    }
    exp = _running_experience()
    exp["audiences"] = ["a1"]
    snap = _snapshot([exp], audiences=[aud])
    assert select_experience("exp-one", snap, visitor_id="v1", visitor_attributes={"country": "CA"}) is None
    assert select_experience("exp-one", snap, visitor_id="v1", visitor_attributes={"country": "US"}) is not None


def test_experience_without_running_variations_returns_none():
    exp = {"id": "e1", "key": "exp-one", "variations": []}
    snap = _snapshot([exp])
    assert select_experience("exp-one", snap, visitor_id="visitor-1") is None


def test_zero_traffic_variations_excluded():
    exp = {
        "id": "e1",
        "key": "exp-one",
        "variations": [{"id": "v1", "key": "off", "traffic_allocation": 0}],
    }
    snap = _snapshot([exp])
    # Only variation has zero traffic -> no bucket -> None (normal miss).
    assert select_experience("exp-one", snap, visitor_id="visitor-1") is None


def test_missing_traffic_allocation_treated_as_full():
    exp = {
        "id": "e1",
        "key": "exp-one",
        "variations": [{"id": "v1", "key": "only"}],
    }
    snap = _snapshot([exp])
    result = select_experience("exp-one", snap, visitor_id="visitor-1")
    assert result is not None
    assert result.variation_id == "v1"


def test_selection_does_not_mutate_snapshot():
    exp = _running_experience()
    snap = _snapshot([exp])
    before = snap.get_experience_by_key("exp-one")
    select_experience("exp-one", snap, visitor_id="visitor-1")
    after = snap.get_experience_by_key("exp-one")
    assert before == after
