"""qs-02 PY-3 — ``get_preview_decision`` pure forced-variation decision
primitive (AC3, AC4, AC7-variation).

Sibling parity (grounds the primitive's name and shape -- qs-02 is identical
across all six SDKs): the JS reference already ships
``DataManager.getPreviewDecision(experience, variationId)``
(``../javascript-sdk`` branch ``feat/experiment-preview``,
``packages/data/src/data-manager.ts``) and the already-merged Ruby sibling
ships ``DataManager#get_preview_decision`` (``../ruby-sdk``
``lib/convert_sdk/data_manager.rb``, ``wf-rubysdk-qs03``/RB-4) with the exact
same two-argument, snapshot-free signature. This RED phase locks the Python
sibling to the same name/shape: ``get_preview_decision(experience,
variation_id) -> ExperienceResult | None``.

Scope (this task only -- PY-3):

* Given a resolved experience MAPPING (NOT a snapshot -- a preview experience
  fetched via ``?exp=`` may not be registered in the installed config; PY-4's
  job) and a numeric-id ``variation_id`` string, force-decide that variation,
  bypassing audiences, segments, locations, experience status, variation
  status/traffic filters, and the bucketing hash entirely.
* Unknown ``variation_id`` -> ``None``. No logging (PY-5 logs the warning at
  the ``Context.set_preview`` call site) and no side effects (no store, no
  tracker -- this primitive does not accept those collaborators at all).
* Return shape IDENTICAL to :class:`~convert_sdk.domain.results.ExperienceResult`,
  the same typed result a normal :func:`~convert_sdk.evaluation.experiences.select_experience`
  bucketing call returns.

Explicitly OUT of scope for this primitive (verified empirically against
``evaluation/experiences.py`` and ``evaluation/rules.py`` before writing these
tests -- see the decision log I8 entry):

* An "environment check" and an "experience status" gate are named in the
  qs-02 contract's bypass list, but NEITHER currently exists as an enforced
  filter anywhere in ``select_experience``/``qualifies`` -- ``environment`` is
  read only for ``Context`` diagnostics reporting (``context.py``), never as a
  qualification filter, and no code path rejects a ``draft``/``paused``
  experience today. The parametrized cases below still cover both fields (they
  cost nothing and lock the forward-compat invariant that, if such a gate is
  ever added to the normal path, this primitive must keep bypassing it) but
  they are NOT currently proving a bypass of live enforcement -- only variation
  ``status``/``traffic_allocation`` are actually enforced today (via
  ``_is_running``/``_has_traffic`` in the packed-layout builder).
* "A visitor with a different stored decision" (also in the qs-02 AC4 list) is
  a ``Context``/``DataStore`` precedence concern -- this primitive takes no
  ``visitor_id`` and no store collaborator, so stored-decision precedence is
  satisfied by construction, not something a unit test of this primitive alone
  can exercise. That is PY-5's integration-level test.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation import experiences
from convert_sdk.evaluation.experiences import select_experience


def _snapshot(experiences_list):
    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": list(experiences_list),
        }
    )


def _preview_experience(
    *,
    experience_status: str = "running",
    environment: Optional[str] = None,
    variation_status: str = "running",
    traffic_allocation: float = 50.0,
) -> "Dict[str, Any]":
    """A synthetic ``?exp=``-shaped experience carrying, on its one variation,
    every gate a normal decision would enforce -- draft/paused status,
    mismatched environment, a non-running variation, zero traffic -- so a
    single forced call proves the bypass for that gate.
    """
    variation: "Dict[str, Any]" = {
        "id": "v1",
        "key": "var-a",
        "status": variation_status,
        "traffic_allocation": traffic_allocation,
        "changes": {"css": "preview"},
    }
    experience: "Dict[str, Any]" = {
        "id": "e1",
        "key": "preview-exp",
        "status": experience_status,
        "variations": [variation],
    }
    if environment is not None:
        experience["environment"] = environment
    return experience


# --- AC4: full bypass -- status, environment, non-running, zero-traffic ------


@pytest.mark.parametrize(
    ("experience_status", "environment", "variation_status", "traffic_allocation"),
    [
        pytest.param("draft", None, "running", 50.0, id="draft-experience-status"),
        pytest.param("paused", None, "running", 50.0, id="paused-experience-status"),
        pytest.param("running", "staging", "running", 50.0, id="mismatched-environment"),
        pytest.param("running", None, "stopped", 50.0, id="non-running-variation"),
        pytest.param("running", None, "running", 0.0, id="zero-traffic-variation"),
    ],
)
def test_forces_variation_bypassing_every_gate(
    experience_status: str,
    environment: Optional[str],
    variation_status: str,
    traffic_allocation: float,
) -> None:
    experience = _preview_experience(
        experience_status=experience_status,
        environment=environment,
        variation_status=variation_status,
        traffic_allocation=traffic_allocation,
    )

    result = experiences.get_preview_decision(experience, "v1")

    assert result is not None
    assert isinstance(result, ExperienceResult)
    assert result.experience_id == "e1"
    assert result.experience_key == "preview-exp"
    assert result.variation_id == "v1"
    assert result.variation_key == "var-a"
    assert result.variation["status"] == variation_status
    assert result.variation["traffic_allocation"] == traffic_allocation


# --- AC7-variation: unknown id -> None, no logging, no side effects ----------


def test_unknown_variation_id_returns_none() -> None:
    experience = _preview_experience()
    assert experiences.get_preview_decision(experience, "does-not-exist") is None


def test_unknown_variation_id_performs_no_logging(caplog: pytest.LogCaptureFixture) -> None:
    """The primitive itself never logs on a miss -- PY-5's ``Context.set_preview``
    is the one that logs the warning for bad input (qs-02 AC7)."""
    experience = _preview_experience()
    with caplog.at_level("WARNING"):
        experiences.get_preview_decision(experience, "does-not-exist")
    assert caplog.records == []


# --- purity: no bucketing hash, no collaborators, no mutation ----------------


def test_never_calls_the_bucketing_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "get_preview_decision must never call the bucketing hash"
        )

    monkeypatch.setattr(experiences, "get_bucket_value_for_visitor", _boom)
    monkeypatch.setattr(experiences, "select_bucket", _boom)
    monkeypatch.setattr(experiences, "select_bucket_anchored", _boom)

    experience = _preview_experience()
    result = experiences.get_preview_decision(experience, "v1")

    assert result is not None
    assert result.variation_id == "v1"


def test_signature_has_no_store_or_tracker_collaborator() -> None:
    """By construction: the primitive accepts only ``(experience,
    variation_id)`` -- there is no ``DataStore``/``Tracker``/``EventBus``
    parameter for it to call through, so "no tracking, no persistence" holds
    structurally rather than needing a spy."""
    sig = inspect.signature(experiences.get_preview_decision)
    assert list(sig.parameters) == ["experience", "variation_id"]


def test_does_not_mutate_the_passed_experience() -> None:
    experience = _preview_experience()
    before = {
        **experience,
        "variations": [dict(v) for v in experience["variations"]],
    }

    experiences.get_preview_decision(experience, "v1")

    assert experience == before


# --- AC3: return shape identical to a normal bucketed decision --------------


def test_shape_matches_a_normal_bucketed_decision() -> None:
    """Grounds AC3's "return shape identical to a normal bucketed decision":
    resolve the SAME variation once through the real ``select_experience``
    bucketing path and once through ``get_preview_decision``, and assert the
    two typed results compare equal field-for-field. Bucketing is
    deterministic, so for a single-variation, full-traffic, unqualified-free
    experience the two paths pick the identical variation -- there is no
    bucketing-derived randomness to subtract out.
    """
    raw_experience = {
        "id": "e1",
        "key": "exp-one",
        "variations": [
            {"id": "v1", "key": "control", "traffic_allocation": 100.0}
        ],
    }
    snap = _snapshot([raw_experience])

    normal = select_experience("exp-one", snap, visitor_id="visitor-1")
    assert normal is not None  # sanity: the normal path resolves deterministically

    forced = experiences.get_preview_decision(raw_experience, normal.variation_id)

    assert forced is not None
    assert isinstance(forced, ExperienceResult)
    assert forced == normal
