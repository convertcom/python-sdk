"""Unit tests for typed results and snapshot-backed experience selection.

Story 1.4, SDK-3. Covers the typed :class:`ExperienceResult` model and the
``evaluation.experiences.select_experience`` selector: qualified visitors get a
typed result, normal misses return ``None``, selection is deterministic for the
same visitor + snapshot, results are typed objects (never raw config dicts), and
selection never mutates the snapshot.
"""

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation.bucketing import (
    get_bucket_value_for_visitor as _real_get_bucket_value_for_visitor,
)
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


# --- sticky-bucketing read-back (qs-03 PY-2: AC2, AC4, AC8, AC9) -------------
#
# select_experience gains a new optional keyword-only ``sticky_bucketing``
# param: a plain ``{experience_id: variation_id}`` mapping. When a stored
# variation id resolves against the CURRENT experience, the hash is skipped
# entirely (AC2). When it does not resolve, the fresh hash path runs (AC4).
# Qualification still gates ahead of the sticky read (AC8). Omitting the
# param (or passing None) must be byte-identical to the pre-qs-03 behavior
# (AC9). These tests currently FAIL because `select_experience` does not yet
# accept `sticky_bucketing` — RED phase, see qs-03 PY-2.


class _HashCallSpy:
    """Wraps the real bucketing hash so tests can assert call counts while
    still exercising the genuine deterministic hash on the fall-through path
    (AC4) -- a bare no-op stub would defeat that assertion.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return _real_get_bucket_value_for_visitor(*args, **kwargs)


def _two_variation_experience(experience_id="e1"):
    return {
        "id": experience_id,
        "key": "exp-one",
        "variations": [
            {"id": "v1", "key": "control", "traffic_allocation": 50.0},
            {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
        ],
    }


def _spy_on_hash(monkeypatch):
    """Patch the hash entry point ``select_experience`` calls and return the
    spy so callers can assert its call count (AC2 zero-calls / AC4 >=1 call).
    """
    spy = _HashCallSpy()
    monkeypatch.setattr(
        "convert_sdk.evaluation.experiences.get_bucket_value_for_visitor", spy
    )
    return spy


def _country_us_audience():
    return {
        "id": "a1",
        "key": "aud",
        "rules": {
            "OR": [
                {
                    "AND": [
                        {
                            "OR_WHEN": [
                                {
                                    "matching": {
                                        "match_type": "equals",
                                        "negated": False,
                                    },
                                    "key": "country",
                                    "value": "US",
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("sticky_map", "expect_hash_called", "expect_variation_ids"),
    [
        pytest.param(
            {"e1": "v1"},
            False,
            {"v1"},
            id="ac2-resolvable-stored-vid-skips-hash-entirely",
        ),
        pytest.param(
            {"e1": "v999-absent-from-config"},
            True,
            {"v1", "v2"},
            id="ac4-unresolvable-stored-vid-falls-through-to-real-hash",
        ),
    ],
)
def test_sticky_bucketing_read_back(
    monkeypatch, sticky_map, expect_hash_called, expect_variation_ids
):
    snap = _snapshot([_two_variation_experience()])
    spy = _spy_on_hash(monkeypatch)

    result = select_experience(
        "exp-one",
        snap,
        visitor_id="visitor-1",
        sticky_bucketing=sticky_map,
    )

    assert result is not None
    assert result.experience_key == "exp-one"
    assert result.experience_id == "e1"
    assert result.variation_id in expect_variation_ids
    assert (spy.calls > 0) is expect_hash_called


def test_sticky_bucketing_resolvable_vid_returns_stored_decision_verbatim():
    # AC2: the returned decision matches the stored variation exactly, not
    # merely "any resolvable variation" -- pinning the specific id/key.
    snap = _snapshot([_two_variation_experience()])
    result = select_experience(
        "exp-one",
        snap,
        visitor_id="visitor-1",
        sticky_bucketing={"e1": "v2"},
    )
    assert result is not None
    assert result.variation_id == "v2"
    assert result.variation_key == "treatment"


def test_sticky_bucketing_does_not_bypass_qualification(monkeypatch):
    # AC8: a stored decision for an experience the visitor no longer
    # qualifies for must NOT resurrect a result -- qualification gates ahead
    # of the sticky read-back.
    exp = _two_variation_experience()
    exp["audiences"] = ["a1"]
    snap = _snapshot([exp], audiences=[_country_us_audience()])
    spy = _spy_on_hash(monkeypatch)

    result = select_experience(
        "exp-one",
        snap,
        visitor_id="visitor-1",
        visitor_attributes={"country": "CA"},
        sticky_bucketing={"e1": "v1"},
    )

    assert result is None
    assert spy.calls == 0


def test_sticky_bucketing_none_is_byte_identical_to_omitted_param():
    # AC9: passing sticky_bucketing=None (or omitting it) must not change the
    # fresh-hash outcome for the same visitor/snapshot.
    snap = _snapshot([_two_variation_experience()])
    baseline = select_experience("exp-one", snap, visitor_id="visitor-42")
    explicit_none = select_experience(
        "exp-one", snap, visitor_id="visitor-42", sticky_bucketing=None
    )
    assert baseline is not None and explicit_none is not None
    assert baseline == explicit_none
