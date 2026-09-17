"""Per-call control matrix (CAP-4): the 11 per-call controls against all six
``Context`` evaluation surfaces.

The declarative table below is the single source of truth for two things a
sibling story each froze independently: which controls a surface accepts
(CAP-1's ``experience_keys`` and CAP-2's ``type_casting`` on the feature pair;
the experience pair's ``enable_tracking``/``enable_storage`` predate this
workflow), and why the five controls no surface accepts stay absent rather
than being added piecemeal. Six signature tests below are DERIVED from the
table rather than hand-written, so a drift between a signature and its
documented disposition fails here first.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import pytest

import convert_sdk.context as context_module
from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context

HONOURED = "honoured"
ABSENT = "absent"
NA = "n/a"

R1 = "the feature-resolution path performs no tracking and no persistence, so the flag would be inert on that surface"
R2 = "the control is absent from every entry point in the package; adding it to the feature pair alone would manufacture the very experience/feature asymmetry this work removes"
R3 = "feature-scoped by definition -- the experience surfaces have no feature/variable concept for it to act on"
R4 = "narrower than R3: the diagnostic returns a reason and no variables, so the flag could not change its verdict"

SURFACES = (
    "run_experience",
    "run_experiences",
    "run_feature",
    "run_features",
    "diagnose_experience",
    "diagnose_feature",
)


@dataclass(frozen=True)
class _Disposition:
    state: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class _ControlRow:
    control: str
    by_surface: Dict[str, _Disposition] = field(default_factory=dict)


def _all(state: str, reason: Optional[str] = None) -> Dict[str, _Disposition]:
    return {surface: _Disposition(state, reason) for surface in SURFACES}


TABLE: List[_ControlRow] = [
    _ControlRow("attributes", _all(HONOURED)),
    _ControlRow("location_attributes", _all(HONOURED)),
    _ControlRow(
        "enable_tracking",
        {
            "run_experience": _Disposition(HONOURED),
            "run_experiences": _Disposition(HONOURED),
            "run_feature": _Disposition(ABSENT, R1),
            "run_features": _Disposition(ABSENT, R1),
            "diagnose_experience": _Disposition(ABSENT, R1),
            "diagnose_feature": _Disposition(ABSENT, R1),
        },
    ),
    _ControlRow(
        "enable_storage",
        {
            "run_experience": _Disposition(HONOURED),
            "run_experiences": _Disposition(HONOURED),
            "run_feature": _Disposition(ABSENT, R1),
            "run_features": _Disposition(ABSENT, R1),
            "diagnose_experience": _Disposition(ABSENT, R1),
            "diagnose_feature": _Disposition(ABSENT, R1),
        },
    ),
    _ControlRow(
        "experience_keys",
        {
            "run_experience": _Disposition(NA, R3),
            "run_experiences": _Disposition(NA, R3),
            "run_feature": _Disposition(HONOURED),
            "run_features": _Disposition(HONOURED),
            "diagnose_experience": _Disposition(NA, R3),
            "diagnose_feature": _Disposition(HONOURED),
        },
    ),
    _ControlRow(
        "type_casting",
        {
            "run_experience": _Disposition(NA, R3),
            "run_experiences": _Disposition(NA, R3),
            "run_feature": _Disposition(HONOURED),
            "run_features": _Disposition(HONOURED),
            "diagnose_experience": _Disposition(NA, R3),
            "diagnose_feature": _Disposition(ABSENT, R4),
        },
    ),
    _ControlRow("update_visitor_properties", _all(ABSENT, R2)),
    _ControlRow("environment", _all(ABSENT, R2)),
    _ControlRow("force_variation_id", _all(ABSENT, R2)),
    _ControlRow("ignore_location_properties", _all(ABSENT, R2)),
    _ControlRow("suppress_events", _all(ABSENT, R2)),
]

# The positional key parameter each surface takes ahead of its keyword-only
# controls, if any (``None`` for the two "all applicable" surfaces).
_POSITIONAL_KEY: Dict[str, Optional[str]] = {
    "run_experience": "experience_key",
    "run_experiences": None,
    "run_feature": "feature_key",
    "run_features": None,
    "diagnose_experience": "experience_key",
    "diagnose_feature": "feature_key",
}


def _expected_params_for(surface: str) -> set[str]:
    """Derive a surface's expected parameter set FROM the table above."""
    params = {"self"}
    key_param = _POSITIONAL_KEY[surface]
    if key_param is not None:
        params.add(key_param)
    for row in TABLE:
        if row.by_surface[surface].state == HONOURED:
            params.add(row.control)
    return params


# ---------------------------------------------------------------------------
# Meta-assertion: every row covers all six surfaces, no cell silently omitted.
# ---------------------------------------------------------------------------


def test_every_row_specifies_a_disposition_for_all_six_surfaces():
    for row in TABLE:
        assert set(row.by_surface) == set(SURFACES), row.control


# ---------------------------------------------------------------------------
# Six signature-set-equality tests, derived from the table.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", SURFACES)
def test_surface_signature_matches_table_disposition(surface):
    method = getattr(Context, surface)
    actual = set(inspect.signature(method).parameters)
    assert actual == _expected_params_for(surface)


@pytest.mark.parametrize("name", ["run_feature", "run_features", "diagnose_feature"])
def test_docstring_args_match_signature(name):
    """Every keyword param is documented, and no documented param is stale."""
    method = getattr(Context, name)
    sig_params = set(inspect.signature(method).parameters) - {"self"}
    entries = method.__doc__.split("Args:\n", 1)[1].split("\n\n", 1)[0]
    indent = len(entries) - len(entries.lstrip(" "))
    documented = set(re.findall(rf"^ {{{indent}}}(\w+):", entries, re.MULTILINE))
    assert documented == sig_params


# ---------------------------------------------------------------------------
# Shared fixtures for the behavioral cases.
# ---------------------------------------------------------------------------

_FEATURE_ID = "feat-one"
_FEATURE_KEY = "feature-one"
_EXPERIENCE_ID = "exp-one"
_EXPERIENCE_KEY = "experience-one"
_VARIATION_ID = "var-one"
_VARIATION_KEY = "variant-one"


def _change() -> Dict[str, Any]:
    return {
        "id": "c-one",
        "type": "fullStackFeature",
        "data": {"feature_id": _FEATURE_ID, "variables_data": {"flag": "on"}},
    }


def _config() -> Dict[str, Any]:
    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": [
            {
                "id": _EXPERIENCE_ID,
                "key": _EXPERIENCE_KEY,
                "variations": [
                    {
                        "id": _VARIATION_ID,
                        "key": _VARIATION_KEY,
                        "traffic_allocation": 100.0,
                        "changes": [_change()],
                    }
                ],
            }
        ],
        "features": [
            {"id": _FEATURE_ID, "key": _FEATURE_KEY, "variables": [{"key": "flag", "type": "string"}]}
        ],
    }


def _ctx(
    visitor_id: str = "visitor-1",
    tracker: Any = None,
    data_store: Any = None,
) -> Context:
    snapshot = load_snapshot(_config())
    return Context(visitor_id, snapshot, tracker=tracker, data_store=data_store)


def _spy(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Mapping[str, Any]]:
    """Wrap ``convert_sdk.context.<name>`` to record every call's kwargs,
    forwarding to the real implementation so evaluation still resolves.
    """
    calls: List[Mapping[str, Any]] = []
    original = getattr(context_module, name)

    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(context_module, name, _wrapper)
    return calls


class _FakeTracker:
    """Duck-typed tracker double recording ``track_bucketing`` calls only."""

    def __init__(self) -> None:
        self.calls: List[Mapping[str, Any]] = []

    def track_bucketing(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


# ---------------------------------------------------------------------------
# Behavioral cases: an honoured control's value reaches the evaluation seam.
# ---------------------------------------------------------------------------


def test_attributes_reaches_select_experience_via_run_experience(monkeypatch):
    calls = _spy(monkeypatch, "select_experience")
    _ctx().run_experience(_EXPERIENCE_KEY, attributes={"plan": "gold"})
    assert calls and calls[-1]["visitor_attributes"]["plan"] == "gold"


def test_location_attributes_reaches_select_experience_via_run_experience(monkeypatch):
    calls = _spy(monkeypatch, "select_experience")
    _ctx().run_experience(_EXPERIENCE_KEY, location_attributes={"url": "/checkout"})
    assert calls and calls[-1]["location_attributes"]["url"] == "/checkout"


def test_attributes_reaches_select_experience_via_run_experiences(monkeypatch):
    calls = _spy(monkeypatch, "select_experience")
    _ctx().run_experiences(attributes={"plan": "silver"})
    assert calls and all(c["visitor_attributes"]["plan"] == "silver" for c in calls)


def test_enable_tracking_false_suppresses_track_bucketing_on_run_experience():
    tracker = _FakeTracker()
    ctx = _ctx(tracker=tracker)
    result = ctx.run_experience(_EXPERIENCE_KEY, enable_tracking=False)
    assert result is not None
    assert tracker.calls == []


def test_enable_storage_false_suppresses_data_store_write_on_run_experience():
    from convert_sdk.adapters.storage.in_memory import InMemoryDataStore
    from convert_sdk.ports.storage import visitor_state_key

    store = InMemoryDataStore()
    ctx = _ctx(data_store=store)
    result = ctx.run_experience(_EXPERIENCE_KEY, enable_storage=False)
    assert result is not None
    assert store.get(visitor_state_key(ctx.visitor_id)) is None


def test_attributes_reaches_resolve_feature_via_run_feature(monkeypatch):
    calls = _spy(monkeypatch, "resolve_feature")
    _ctx().run_feature(_FEATURE_KEY, attributes={"plan": "gold"})
    assert calls and calls[-1]["visitor_attributes"]["plan"] == "gold"


def test_location_attributes_reaches_resolve_feature_via_run_feature(monkeypatch):
    calls = _spy(monkeypatch, "resolve_feature")
    _ctx().run_feature(_FEATURE_KEY, location_attributes={"url": "/checkout"})
    assert calls and calls[-1]["location_attributes"]["url"] == "/checkout"


def test_experience_keys_reaches_resolve_feature_via_run_feature(monkeypatch):
    calls = _spy(monkeypatch, "resolve_feature")
    _ctx().run_feature(_FEATURE_KEY, experience_keys=[_EXPERIENCE_KEY])
    assert calls and list(calls[-1]["experience_keys"]) == [_EXPERIENCE_KEY]


def test_type_casting_reaches_resolve_feature_via_run_feature(monkeypatch):
    calls = _spy(monkeypatch, "resolve_feature")
    _ctx().run_feature(_FEATURE_KEY, type_casting=False)
    assert calls and calls[-1]["type_casting"] is False


def test_experience_keys_and_type_casting_reach_resolve_features_via_run_features(monkeypatch):
    calls = _spy(monkeypatch, "resolve_features")
    _ctx().run_features(experience_keys=[_EXPERIENCE_KEY], type_casting=False)
    assert calls
    assert list(calls[-1]["experience_keys"]) == [_EXPERIENCE_KEY]
    assert calls[-1]["type_casting"] is False
