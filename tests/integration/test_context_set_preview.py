"""qs-02 PY-5 -- ``Context.set_preview`` + forced-decision wiring (RED phase).

Wires PY-2 (``parse_preview_param`` -- not exercised here, the application's
job), PY-3 (``evaluation.experiences.get_preview_decision``), and PY-4
(``HttpxTransport.fetch_config_by_experience`` + its process-wide 60s memo)
into the public ``Context`` surface:

* AC3 -- forced decision. A DRAFT experience delivered ONLY via the ``?exp=``
  fetch (mocked transport) resolves through ``run_experience`` on the preview
  context.
* AC4 -- full bypass. Draft/paused status, mismatched ``environment``,
  non-running variation, zero-traffic variation, AND a visitor whose own
  deterministic bucketing hash would otherwise select a DIFFERENT variation
  (this SDK has no real stored/sticky-decision mechanism --
  ``tests/test_anchored_experience_selection.py``
  ``test_select_experience_has_no_stored_or_forced_variation_override_today``
  already established that faithfully; the closest real analogue to "a visitor
  with a different stored decision" is the visitor's own deterministic
  bucketing-hash outcome, which this file proves preview still overrides).
* AC6 -- isolation. A concurrent NON-preview ``Context`` from the SAME ``Core``
  buckets/returns NORMAL decisions (no leak of preview state across
  contexts), and OTHER experiences on the SAME preview context decide
  normally.
* AC7 -- inert on bad input. An unresolvable experience id (absent locally AND
  absent from the ``?exp=`` fetch response), an unknown variation id, a failed
  fetch (transport error), and empty-string ids all degrade to a logged
  WARNING with fully normal behavior preserved -- never an exception.
* AC10-relevant -- ``diagnose_*`` output is unchanged for non-preview flows.

Explicitly OUT of scope for this file (PY-6's job, per the task brief): the
zero-trace suppression of tracking/persistence for a preview context (AC5).
No assertions here about tracker/DataStore call counts.

All HTTP is mocked at the RESPX route level via the shared qs-06 integration
harness (``tests/integration/conftest.py``) -- no real network. Since PY-4's
``?exp=`` memo is a PROCESS-WIDE module-level cache (``httpx_transport.py``
``_CONFIG_BY_EXPERIENCE_CACHE``), this file clears it before/after every test
(mirroring ``tests/test_config_by_experience_memo.py``'s own autouse fixture)
so no test's fetch is silently satisfied by another test's cached entry
(the exact test-isolation defect flagged in decision-log I18, swept
proactively here rather than discovered later).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
import pytest

from convert_sdk.adapters.transport import httpx_transport as httpx_transport_module
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.core import Core, _find_experience_in_body
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation.experiences import select_experience

from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL, SDK_KEY


@pytest.fixture(autouse=True)
def _clear_process_wide_preview_memo():
    with httpx_transport_module._CONFIG_BY_EXPERIENCE_LOCK:
        httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE.clear()
    yield
    with httpx_transport_module._CONFIG_BY_EXPERIENCE_LOCK:
        httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE.clear()


# --- config-building helpers (local, direct-config mode; no network) --------


def _variation(
    variation_id: str,
    key: str,
    *,
    status: str = "running",
    traffic_allocation: float = 100.0,
) -> Dict[str, Any]:
    return {
        "id": variation_id,
        "key": key,
        "status": status,
        "traffic_allocation": traffic_allocation,
        "changes": {},
    }


def _experience(
    experience_id: str,
    key: str,
    *,
    status: str = "running",
    environment: Optional[str] = None,
    variations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    experience: Dict[str, Any] = {
        "id": experience_id,
        "key": key,
        "status": status,
        "variations": variations if variations is not None else [_variation("v1", "control")],
    }
    if environment is not None:
        experience["environment"] = environment
    return experience


def _config(experiences: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": experiences,
        "features": [],
        "goals": [],
        "audiences": [],
        "segments": [],
    }


def _find_visitor_bucketing_into(
    experience_key: str,
    variation_id: str,
    raw_config: Dict[str, Any],
    *,
    max_attempts: int = 200,
) -> str:
    """Find a real visitor id whose DETERMINISTIC bucketing hash would select
    ``variation_id`` for ``experience_key`` under normal (non-preview)
    evaluation against ``raw_config`` -- the only real analogue this SDK has
    to "a visitor with a different stored decision" (no sticky-storage
    mechanism exists; see this module's docstring)."""
    snapshot = load_snapshot(raw_config)
    for i in range(max_attempts):
        candidate = f"stored-decision-visitor-{i}"
        result = select_experience(experience_key, snapshot, visitor_id=candidate)
        if result is not None and result.variation_id == variation_id:
            return candidate
    raise AssertionError(
        f"no visitor id among the first {max_attempts} candidates naturally "
        f"buckets into variation {variation_id!r} -- widen the search or "
        "adjust the traffic split"
    )


def _direct_core(raw_config: Dict[str, Any]) -> Core:
    return Core(SDKConfig(data=raw_config)).initialize()


def _remote_core(*, transport: HttpxTransport) -> Core:
    return Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
        ),
        transport=transport,
    ).initialize()


# --- _find_experience_in_body pure helper (defensive hardening, code review) -
#
# Regression lock for a footgun found in review: ``str(experience.get("id"))
# == str(experience_id)`` would coerce a MISSING or ``null`` id to the string
# "None", falsely matching a lookup for the literal experience_id "None". The
# helper backs ``Core._resolve_preview_experience`` (this file's PY-5 fetch-
# through path), so it is exercised here at the unit level -- no Core/HTTP
# setup needed since it is a pure function of a raw config body.


@pytest.mark.parametrize(
    ("body", "experience_id", "expect_match"),
    [
        pytest.param(
            {"experiences": [{"key": "no-id-exp"}]},
            "None",
            False,
            id="missing_id_key_never_matches_literal_none_lookup",
        ),
        pytest.param(
            {"experiences": [{"id": None, "key": "null-id-exp"}]},
            "None",
            False,
            id="explicit_null_id_never_matches_literal_none_lookup",
        ),
        pytest.param(
            {"experiences": [{"id": "123", "key": "numeric-id-exp"}]},
            "123",
            True,
            id="normal_numeric_string_id_still_matches",
        ),
        pytest.param(
            {"key": "no-experiences-list"},
            "123",
            False,
            id="body_missing_experiences_list",
        ),
        pytest.param(
            {"experiences": "not-a-list"},
            "123",
            False,
            id="experiences_field_not_a_list",
        ),
    ],
)
def test_find_experience_in_body_id_matching(
    body: Dict[str, Any], experience_id: str, expect_match: bool
) -> None:
    """``_find_experience_in_body`` never falsely matches an id-less
    experience against the literal lookup string ``"None"``, while a normal
    numeric-string id still matches -- guarding the helper's own docstring
    contract ('Returns None on any miss ... never raises.')."""
    result = _find_experience_in_body(body, experience_id)
    if expect_match:
        assert result is not None
        assert result["id"] == experience_id
    else:
        assert result is None


# --- AC4: full bypass -- status, environment, non-running, zero-traffic -----


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
def test_run_experience_forces_variation_bypassing_every_gate(
    experience_status: str,
    environment: Optional[str],
    variation_status: str,
    traffic_allocation: float,
) -> None:
    experience = _experience(
        "e-bypass",
        "bypass-key",
        status=experience_status,
        environment=environment,
        variations=[
            _variation(
                "v-forced",
                "var-forced",
                status=variation_status,
                traffic_allocation=traffic_allocation,
            )
        ],
    )
    core = _direct_core(_config([experience]))
    try:
        ctx = core.create_context("visitor-bypass")
        ctx.set_preview("e-bypass", "v-forced")

        result = ctx.run_experience("bypass-key")

        assert result is not None
        assert isinstance(result, ExperienceResult)
        assert result.experience_key == "bypass-key"
        assert result.experience_id == "e-bypass"
        assert result.variation_id == "v-forced"
        assert result.variation_key == "var-forced"
    finally:
        core.close()


def test_run_experience_forces_variation_even_when_visitor_would_normally_bucket_differently() -> None:
    """AC4's "a visitor with a different stored decision" case, grounded in
    this SDK's ACTUAL determinism-only bucketing (no sticky storage exists --
    see module docstring): finds a real visitor id whose normal bucketing hash
    selects "var-b", then proves the SAME visitor gets "var-a" once preview is
    set for that experience.
    """
    experience = _experience(
        "e-stored",
        "stored-key",
        variations=[
            _variation("v-a", "var-a", traffic_allocation=50.0),
            _variation("v-b", "var-b", traffic_allocation=50.0),
        ],
    )
    raw_config = _config([experience])
    visitor_id = _find_visitor_bucketing_into("stored-key", "v-b", raw_config)

    # Sanity: confirm the normal (non-preview) path really does select v-b for
    # this visitor before proving preview overrides it.
    baseline_core = _direct_core(raw_config)
    try:
        baseline = baseline_core.create_context(visitor_id).run_experience("stored-key")
        assert baseline is not None
        assert baseline.variation_id == "v-b"
    finally:
        baseline_core.close()

    core = _direct_core(raw_config)
    try:
        ctx = core.create_context(visitor_id)
        ctx.set_preview("e-stored", "v-a")

        result = ctx.run_experience("stored-key")

        assert result is not None
        assert result.variation_id == "v-a"
    finally:
        core.close()


# --- AC3: forced decision via a fetch-only (?exp=) draft experience ---------


def test_run_experience_forces_variation_delivered_only_via_exp_fetch(
    respx_mock, minimal_config
) -> None:
    draft_experience = _experience(
        "e-draft",
        "draft-key",
        status="draft",
        variations=[_variation("v-draft", "var-draft", traffic_allocation=100.0)],
    )
    exp_scoped_body = _config([draft_experience])

    def _config_side_effect(request: httpx.Request) -> httpx.Response:
        if "exp" in request.url.params:
            return httpx.Response(200, json=exp_scoped_body)
        return httpx.Response(200, json=minimal_config)

    respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(side_effect=_config_side_effect)

    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core(transport=transport)
    try:
        ctx = core.create_context("visitor-draft")
        ctx.set_preview("e-draft", "v-draft")

        result = ctx.run_experience("draft-key")

        assert result is not None
        assert result.experience_key == "draft-key"
        assert result.experience_id == "e-draft"
        assert result.variation_id == "v-draft"
    finally:
        core.close()


def test_run_experiences_includes_forced_result_for_an_already_local_preview_target(
) -> None:
    """The ``run_experiences()`` companion of AC3/AC4, scoped to the case that
    IS applicable to bulk evaluation: the preview target already lives in the
    loaded snapshot (so it naturally appears in ``run_experiences()``'s
    iteration over ``snapshot.experiences``). The fetch-only-draft scenario
    (AC3 proper) is exercised only through ``run_experience`` above -- see
    this task's report for why bulk evaluation of a snapshot-absent preview
    target is left as an open design question, not silently decided here.
    """
    target = _experience(
        "e-bulk-target",
        "bulk-target-key",
        variations=[_variation("v-forced", "var-forced", traffic_allocation=100.0)],
    )
    other = _experience(
        "e-bulk-other",
        "bulk-other-key",
        variations=[_variation("v-other", "var-other", traffic_allocation=100.0)],
    )
    raw_config = _config([target, other])

    core = _direct_core(raw_config)
    try:
        ctx = core.create_context("visitor-bulk")
        ctx.set_preview("e-bulk-target", "v-forced")

        results = {r.experience_key: r for r in ctx.run_experiences()}

        assert results["bulk-target-key"].variation_id == "v-forced"
        assert results["bulk-other-key"].variation_id == "v-other"
    finally:
        core.close()


def test_run_experiences_synthesizes_forced_result_for_a_fetch_only_preview_target(
    respx_mock,
) -> None:
    """Decision I27's post-loop synthesis branch: when the preview target is
    NOT present in the local snapshot (resolved only via the ``?exp=`` fetch,
    mirroring AC3's ``test_run_experience_forces_variation_delivered_only_via_exp_fetch``),
    ``run_experiences()`` must APPEND the already-resolved forced result to its
    output rather than replace it -- proven by asserting the forced target
    AND a separate, normally-loaded local experience are BOTH present.
    """
    other = _experience(
        "e-other-local",
        "other-local-key",
        variations=[_variation("v-other", "var-other", traffic_allocation=100.0)],
    )
    local_config = _config([other])

    draft_experience = _experience(
        "e-fetch-only",
        "fetch-only-key",
        status="draft",
        variations=[_variation("v-draft", "var-draft", traffic_allocation=100.0)],
    )
    exp_scoped_body = _config([draft_experience])

    def _config_side_effect(request: httpx.Request) -> httpx.Response:
        if "exp" in request.url.params:
            return httpx.Response(200, json=exp_scoped_body)
        return httpx.Response(200, json=local_config)

    respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(side_effect=_config_side_effect)

    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core(transport=transport)
    try:
        ctx = core.create_context("visitor-fetch-only-bulk")
        ctx.set_preview("e-fetch-only", "v-draft")

        results = {r.experience_key: r for r in ctx.run_experiences()}

        assert results["fetch-only-key"].variation_id == "v-draft"
        assert results["other-local-key"].variation_id == "v-other"
    finally:
        core.close()


# --- AC6: isolation ----------------------------------------------------------


def test_concurrent_non_preview_context_from_same_core_decides_normally() -> None:
    """A SEPARATE ``Context`` created from the SAME ``Core`` (no shared
    module-level/global preview state) must bucket/return the NORMAL decision
    for the same experience the preview context forces.

    The forced target ("v-forced") is deliberately UNREACHABLE under normal
    evaluation (``status="stopped"``, so ``select_experience`` would never
    naturally pick it) while a SEPARATE variation ("v-normal") is the only one
    normal bucketing can select. This makes the isolation check load-bearing:
    if preview state ever leaked into ``other_ctx``, it would incorrectly
    return the unreachable "v-forced" too, instead of "v-normal".
    """
    experience = _experience(
        "e-isolation",
        "isolation-key",
        variations=[
            _variation("v-normal", "var-normal", status="running", traffic_allocation=100.0),
            _variation("v-forced", "var-forced", status="stopped", traffic_allocation=0.0),
        ],
    )
    raw_config = _config([experience])
    core = _direct_core(raw_config)
    try:
        preview_ctx = core.create_context("visitor-preview")
        preview_ctx.set_preview("e-isolation", "v-forced")
        other_ctx = core.create_context("visitor-plain")

        preview_result = preview_ctx.run_experience("isolation-key")
        other_result = other_ctx.run_experience("isolation-key")

        assert preview_result is not None
        assert other_result is not None
        assert preview_result.variation_id == "v-forced"
        # The load-bearing isolation assertion: no leak means the plain
        # context is oblivious to the other context's forced target.
        assert other_result.variation_id == "v-normal"
    finally:
        core.close()


def test_other_experiences_on_the_same_preview_context_decide_normally() -> None:
    experience_a = _experience(
        "e-preview-target",
        "preview-target-key",
        variations=[_variation("v-forced", "var-forced", traffic_allocation=100.0)],
    )
    experience_b = _experience(
        "e-untouched",
        "untouched-key",
        variations=[_variation("v-normal", "var-normal", traffic_allocation=100.0)],
    )
    raw_config = _config([experience_a, experience_b])

    baseline_core = _direct_core(raw_config)
    try:
        baseline = baseline_core.create_context("visitor-same").run_experience(
            "untouched-key"
        )
    finally:
        baseline_core.close()

    core = _direct_core(raw_config)
    try:
        ctx = core.create_context("visitor-same")
        ctx.set_preview("e-preview-target", "v-forced")

        forced = ctx.run_experience("preview-target-key")
        untouched = ctx.run_experience("untouched-key")

        assert forced is not None
        assert forced.variation_id == "v-forced"
        assert untouched == baseline
    finally:
        core.close()


# --- AC7: inert on bad input --------------------------------------------------


@pytest.mark.parametrize(
    ("experience_id", "variation_id"),
    [
        pytest.param("", "v1", id="empty-experience-id"),
        pytest.param("e1", "", id="empty-variation-id"),
    ],
)
def test_set_preview_with_empty_ids_is_inert_and_warns(
    experience_id: str, variation_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    experience = _experience(
        "e1",
        "real-key",
        variations=[_variation("v1", "var-1", traffic_allocation=100.0)],
    )
    core = _direct_core(_config([experience]))
    try:
        ctx = core.create_context("visitor-empty-ids")
        with caplog.at_level(logging.WARNING, logger="convert_sdk"):
            ctx.set_preview(experience_id, variation_id)

        assert any("preview" in r.getMessage().lower() for r in caplog.records)

        # Normal behavior preserved: the real experience still resolves
        # exactly as it would with no preview ever set.
        result = ctx.run_experience("real-key")
        assert result is not None
        assert result.variation_id == "v1"
    finally:
        core.close()


def test_set_preview_unknown_variation_id_on_a_local_experience_is_inert_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    experience = _experience(
        "e-known",
        "known-key",
        variations=[_variation("v1", "var-1", traffic_allocation=100.0)],
    )
    core = _direct_core(_config([experience]))
    try:
        ctx = core.create_context("visitor-bad-variation")
        with caplog.at_level(logging.WARNING, logger="convert_sdk"):
            ctx.set_preview("e-known", "does-not-exist")

        assert any("preview" in r.getMessage().lower() for r in caplog.records)

        # Inert: the experience decides NORMALLY (100% traffic -> v1), not a
        # crash and not a forced miss.
        result = ctx.run_experience("known-key")
        assert result is not None
        assert result.variation_id == "v1"
    finally:
        core.close()


def test_set_preview_unresolvable_experience_id_is_inert_and_warns(
    respx_mock, minimal_config, caplog: pytest.LogCaptureFixture
) -> None:
    """Neither in the local config NOR found in the ``?exp=`` fetch response
    (the fetch succeeds but returns a body with no matching experience id)."""
    respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json=minimal_config)
    )
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core(transport=transport)
    try:
        ctx = core.create_context("visitor-unresolvable")
        with caplog.at_level(logging.WARNING, logger="convert_sdk"):
            ctx.set_preview("does-not-exist-anywhere", "v1")

        assert any("preview" in r.getMessage().lower() for r in caplog.records)

        # No exception, and a request for a truly nonexistent experience key
        # still returns the normal miss (None), never a crash.
        result = ctx.run_experience("does-not-exist-anywhere")
        assert result is None
    finally:
        core.close()


def test_set_preview_fetch_transport_failure_is_inert_and_warns(
    respx_mock, minimal_config, caplog: pytest.LogCaptureFixture
) -> None:
    """A transient transport/HTTP error on the ``?exp=`` fetch (e.g. a 503)
    must never propagate out of ``set_preview`` -- it degrades to the same
    inert-with-warning contract as an unresolvable id (JS reference parity:
    ``Context.setPreview`` catches ``getConfigByExperience`` errors)."""

    def _config_side_effect(request: httpx.Request) -> httpx.Response:
        if "exp" in request.url.params:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=minimal_config)

    respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(side_effect=_config_side_effect)

    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core(transport=transport)
    try:
        ctx = core.create_context("visitor-fetch-fails")
        with caplog.at_level(logging.WARNING, logger="convert_sdk"):
            ctx.set_preview("e-unreachable", "v1")  # must not raise

        assert any("preview" in r.getMessage().lower() for r in caplog.records)
    finally:
        core.close()


# --- discovered work (decision-log I22 open item): a custom Transport that ---
# --- does NOT implement the additive SupportsPreviewFetch capability --------


class _MinimalTransport:
    """A conforming ``Transport`` implementation that deliberately does NOT
    implement the additive ``SupportsPreviewFetch`` capability (decision I22 --
    ``Transport`` itself never gained a new REQUIRED method for this rare,
    opt-in capability, so an existing/future custom transport implementing only
    the required three methods must keep working). Used to prove ``Core``'s
    ``isinstance(transport, SupportsPreviewFetch)`` duck-check degrades
    gracefully instead of raising an ``AttributeError`` for the missing method
    (RED open item #2 from decision-log I22, resolved by this test).
    """

    def __init__(self, config_body: Dict[str, Any]) -> None:
        self._config_body = config_body
        self.fetch_config_calls = 0

    def fetch_config(self, config: SDKConfig) -> Dict[str, Any]:
        self.fetch_config_calls += 1
        return self._config_body

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> int:
        return 200

    def close(self) -> None:
        return None

    def __enter__(self) -> "_MinimalTransport":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def test_set_preview_custom_transport_without_preview_fetch_capability_is_inert_and_warns(
    minimal_config, caplog: pytest.LogCaptureFixture
) -> None:
    """A snapshot-absent preview target on a ``Core`` wired to a custom
    ``Transport`` lacking ``fetch_config_by_experience`` must degrade to the
    SAME inert-with-warning contract as an unresolvable id -- never an
    ``AttributeError`` for calling a method the transport does not implement."""
    transport = _MinimalTransport(minimal_config)
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
        ),
        transport=transport,
    ).initialize()
    try:
        ctx = core.create_context("visitor-no-preview-capability")
        with caplog.at_level(logging.WARNING, logger="convert_sdk"):
            ctx.set_preview("e-not-local", "v1")  # must not raise

        assert any("preview" in r.getMessage().lower() for r in caplog.records)
        # Only the ordinary init-time config fetch happened -- no ?exp= call
        # was ever attempted against a transport that cannot serve it.
        assert transport.fetch_config_calls == 1
    finally:
        core.close()


# --- AC10-relevant: diagnose_* unchanged for non-preview flows ---------------


def test_diagnose_experience_unchanged_when_preview_never_set() -> None:
    """A light regression smoke test: the full pre-existing diagnostics suite
    (``tests/test_diagnosable_outcomes.py``, ``tests/test_diagnostic_logging.py``)
    is the real AC10 regression lock and must stay green; this only proves the
    new preview wiring did not change ``diagnose_experience``'s ordinary,
    non-preview return shape.
    """
    experience = _experience(
        "e-diag",
        "diag-key",
        variations=[_variation("v1", "var-1", traffic_allocation=100.0)],
    )
    core = _direct_core(_config([experience]))
    try:
        ctx = core.create_context("visitor-diag")
        diagnostic = ctx.diagnose_experience("diag-key")
        assert diagnostic.reason.value == "resolved"
        assert diagnostic.details["variation_key"] == "var-1"
    finally:
        core.close()
