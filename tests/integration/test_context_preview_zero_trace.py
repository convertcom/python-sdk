"""qs-02 PY-6 -- zero-trace hardening for a preview context (RED phase).

PY-5 (``tests/integration/test_context_set_preview.py``) wired
``Context.set_preview`` / the forced-decision path but deliberately left
tracking and persistence flowing through the NORMAL ``Tracker`` /
``_persist_visitor_state`` calls -- that suppression is this task's job
(AC5, AC6).

Once a preview is set (``set_preview`` succeeded), a context must leave ZERO
trace:

* ALL tracking is disabled -- no request ever reaches the track endpoint, and
  this overrides a per-call ``enable_tracking=True``. ``track_conversion`` has
  no ``enable_tracking`` parameter at all, so it must become an UNCONDITIONAL
  no-op under preview.
* ALL visitor-state persistence is disabled -- zero ``DataStore`` WRITES (no
  sticky-bucketing marker, no goal-dedup marker, no segment/attribute write).
  Visitor state may still exist as per-context in-memory scratch.
* Other experiences on the SAME preview context still DECIDE normally -- only
  tracking/persistence is suppressed, not evaluation.
* A concurrent NON-preview ``Context`` from the SAME ``Core`` is UNAFFECTED --
  suppression is per-context, not global (AC6), and the pre-existing
  non-preview tracking/persistence contract is unchanged (AC10).

Per decision P2 (already fixed -- not re-derived here), the gate belongs at
the ``Context`` call sites -- before ``self._tracker.track_bucketing(...)`` in
``run_experience`` / ``run_experiences``, before ``self._tracker.track(...)``
in ``track_conversion``, and inside ``_persist_visitor_state`` -- NOT inside
``Tracker``/``deduplication.py``, because the dedup markers are written INSIDE
those modules; gating there would already have persisted a marker by the time
suppression could apply.

Everything here is expected to FAIL today (RED): PY-5's decision path calls
the tracker/persistence unconditionally, so the spies below observe writes and
POSTs the assertions say must be zero.

Spy approach reused verbatim from the established precedents (do not invent a
new one):

* ``_SpyDataStore`` mirrors ``tests/test_config_by_experience_memo.py``'s
  ``_SpyDataStore`` (records every call so a test can assert a zero-touch
  outcome), extended with ``has``/``delete`` tracking since dedup evaluation
  reads via ``store.has(...)`` before writing via ``store.set(...)``.
* The RESPX transport spy (``mock_tracking_endpoint`` route + its
  ``.calls``) and the ``_experience`` / ``_variation`` config-builder shape
  mirror ``tests/integration/test_context_set_preview.py``.
* The in-process ATEXIT-hook trigger (``_trigger_atexit_flush``) mirrors
  ``tests/integration/test_queue_lifecycle.py``
  ``test_atexit_release_emits_queue_released_reason_atexit`` -- the
  established way to exercise the best-effort ``atexit`` release path without
  relying on real interpreter shutdown.

A single ``Core`` (and therefore a single shared ``Tracker`` + queue) backs
every multi-context test here, so isolation is proven the same way the
codebase already proves it for decisions (AC6 in
``test_context_set_preview.py``): a second, non-preview ``Context`` created
from the SAME ``Core``.
"""

from __future__ import annotations

import atexit
from typing import Any, Dict, List, Optional

import httpx

from convert_sdk import InMemoryDataStore
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.core import Core
from convert_sdk.tracking.flush import register_atexit_flush

from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL, SDK_KEY

# --- config-building helpers (mirrors tests/integration/test_context_set_preview.py) --


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
    variations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "id": experience_id,
        "key": key,
        "status": status,
        "variations": variations if variations is not None else [_variation("v1", "control")],
    }


def _preview_config() -> Dict[str, Any]:
    """The zero-trace fixture config: a forceable target + an untouched other
    experience (both 100% traffic so evaluation is deterministic regardless of
    visitor id), one trackable goal, and one rule-less (always-matching)
    custom segment so every persistence call site (``set_attributes`` /
    ``set_segments`` / ``run_custom_segments``) has something real to write.
    """
    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": [
            _experience(
                "e-target",
                "target-key",
                variations=[_variation("v-forced", "var-forced", traffic_allocation=100.0)],
            ),
            _experience(
                "e-other",
                "other-key",
                variations=[_variation("v-other", "var-other", traffic_allocation=100.0)],
            ),
        ],
        "features": [],
        "goals": [{"id": "g1", "key": "purchase_completed"}],
        "audiences": [],
        "segments": [{"id": "s1", "key": "vip-segment"}],
    }


# --- spy DataStore (mirrors tests/test_config_by_experience_memo.py _SpyDataStore,
# extended with has/delete since dedup evaluation reads via store.has(...)) --------


class _SpyDataStore(InMemoryDataStore):
    """Records every ``get``/``set``/``has``/``delete`` call so a test can
    assert a zero-WRITE outcome (``set_calls``) while still tolerating the
    unrelated, pre-existing ``get`` that ``Core.create_context`` performs to
    rehydrate visitor state -- that read happens for every context regardless
    of preview and is out of this task's scope.
    """

    def __init__(self) -> None:
        super().__init__()
        self.get_calls: List[str] = []
        self.set_calls: List[Any] = []
        self.has_calls: List[str] = []
        self.delete_calls: List[str] = []

    def get(self, key: str) -> Any:
        self.get_calls.append(key)
        return super().get(key)

    def set(self, key: str, value: Any, ttl: Any = None) -> None:
        self.set_calls.append((key, value, ttl))
        super().set(key, value, ttl)

    def has(self, key: str) -> bool:
        self.has_calls.append(key)
        return super().has(key)

    def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        super().delete(key)


# --- Core-construction + atexit-trigger helpers -------------------------------


def _build_core(respx_mock: Any, raw_config: Dict[str, Any], data_store: InMemoryDataStore) -> Core:
    """An initialized, remote (``sdk_key``) ``Core`` wired to ``raw_config`` over
    the RESPX-mocked HTTPS base URL, with a caller-supplied ``DataStore`` spy.
    """
    respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json=raw_config)
    )
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    return Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
            data_store=data_store,
        ),
        transport=transport,
    ).initialize()


def _trigger_atexit_flush(core: Core) -> None:
    """Drive the tracker's ATEXIT release path in-process.

    Mirrors ``tests/integration/test_queue_lifecycle.py``
    ``test_atexit_release_emits_queue_released_reason_atexit`` -- the
    established way to exercise the best-effort ``atexit`` hook (real
    interpreter shutdown cannot be triggered from inside a running test).
    """

    class _AtexitFlushable:
        def flush(self_inner) -> None:  # mirrors tests/integration/test_queue_lifecycle.py
            core._tracker.flush_atexit()  # type: ignore[attr-defined]

    cb = register_atexit_flush(_AtexitFlushable())
    try:
        cb()
    finally:
        atexit.unregister(cb)


# --- AC5: run_experience / run_experiences produce zero trace under preview --


def test_run_experience_and_run_experiences_produce_zero_trace_under_preview(
    respx_mock, mock_tracking_endpoint
) -> None:
    """A per-call ``enable_tracking=True`` must NOT defeat preview suppression
    -- both the forced target AND the untouched other experience must decide
    normally while writing/POSTing nothing, through BOTH ``run_experience``
    and the bulk ``run_experiences`` entry point.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        ctx = core.create_context("visitor-zero-trace")
        ctx.set_preview("e-target", "v-forced")

        target = ctx.run_experience("target-key", enable_tracking=True)
        other = ctx.run_experience("other-key", enable_tracking=True)
        bulk = {r.experience_key: r for r in ctx.run_experiences(enable_tracking=True)}

        assert target is not None
        assert target.variation_id == "v-forced"
        assert other is not None
        assert other.variation_id == "v-other"
        assert bulk["target-key"].variation_id == "v-forced"
        assert bulk["other-key"].variation_id == "v-other"

        core.flush()

        assert spy_store.set_calls == []
        assert spy_store.has_calls == []
        assert len(mock_tracking_endpoint.calls) == 0
    finally:
        core.close()


def test_track_conversion_is_unconditional_noop_under_preview(
    respx_mock, mock_tracking_endpoint
) -> None:
    """``track_conversion`` has no ``enable_tracking`` parameter -- it must be
    an unconditional no-op under preview regardless of ``force_multiple``.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        ctx = core.create_context("visitor-conversion-preview")
        ctx.set_preview("e-target", "v-forced")

        first = ctx.track_conversion("purchase_completed")
        forced_repeat = ctx.track_conversion(
            "purchase_completed", revenue=10.0, force_multiple=True
        )

        core.flush()

        assert first.tracked is False
        assert forced_repeat.tracked is False
        assert spy_store.set_calls == []
        assert spy_store.has_calls == []
        assert len(mock_tracking_endpoint.calls) == 0
    finally:
        core.close()


def test_persist_visitor_state_is_suppressed_for_every_call_site_under_preview(
    respx_mock, mock_tracking_endpoint
) -> None:
    """Every call site that routes through ``_persist_visitor_state``
    (``set_attributes`` / ``set_segments`` / ``run_custom_segments``) must
    write nothing once a preview is set. ``vip-segment`` is rule-less (matches
    unconditionally) so ``run_custom_segments`` has a REAL match to persist if
    suppression is missing -- a no-op call would pass trivially and prove
    nothing.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        ctx = core.create_context("visitor-state-preview")
        ctx.set_preview("e-target", "v-forced")

        ctx.set_attributes({"tier": "gold"})
        ctx.set_segments({"segment": "vip"})
        segments_result = ctx.run_custom_segments(["vip-segment"])

        # The evaluation itself still runs normally (only persistence is
        # suppressed) -- a real match is expected here.
        assert segments_result.matched_segment_ids == ("s1",)
        assert spy_store.set_calls == []
    finally:
        core.close()


def test_full_lifecycle_zero_trace_across_explicit_flush_and_atexit(
    respx_mock, mock_tracking_endpoint
) -> None:
    """The AC5 full-lifecycle proof: every suppressed call site exercised on
    ONE preview context, released through BOTH an explicit ``core.flush()``
    AND the best-effort ``atexit`` hook -- zero writes, zero POSTs, from
    start to (simulated) interpreter shutdown.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        ctx = core.create_context("visitor-full-lifecycle")
        ctx.set_preview("e-target", "v-forced")

        target = ctx.run_experience("target-key", enable_tracking=True)
        other = ctx.run_experience("other-key", enable_tracking=True)
        conversion = ctx.track_conversion("purchase_completed")
        ctx.set_attributes({"tier": "gold"})
        ctx.set_segments({"segment": "vip"})
        ctx.run_custom_segments(["vip-segment"])

        core.flush()
        _trigger_atexit_flush(core)

        assert target is not None
        assert other is not None
        assert conversion.tracked is False
        assert spy_store.set_calls == []
        assert spy_store.has_calls == []
        assert len(mock_tracking_endpoint.calls) == 0
    finally:
        core.close()


# --- AC6: isolation -- suppression is per-context, not global -----------------


def test_concurrent_non_preview_context_persists_and_tracks_while_preview_stays_silent(
    respx_mock, mock_tracking_endpoint
) -> None:
    """A SEPARATE, non-preview ``Context`` from the SAME ``Core`` (same shared
    ``Tracker`` + queue + ``DataStore``) must bucket, persist, and track
    NORMALLY while the preview context on that same ``Core`` produces zero
    trace of its own -- proving the suppression gate is per-context state, not
    a global/Tracker-level switch.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        preview_ctx = core.create_context("visitor-preview-iso")
        preview_ctx.set_preview("e-target", "v-forced")
        other_ctx = core.create_context("visitor-plain-iso")

        preview_result = preview_ctx.run_experience("target-key", enable_tracking=True)
        preview_ctx.track_conversion("purchase_completed")

        other_result = other_ctx.run_experience("other-key", enable_tracking=True)
        other_ctx.track_conversion("purchase_completed")

        core.flush()

        preview_writes = [
            call for call in spy_store.set_calls if "visitor-preview-iso" in str(call[0])
        ]
        other_writes = [
            call for call in spy_store.set_calls if "visitor-plain-iso" in str(call[0])
        ]

        assert preview_result is not None
        assert preview_result.variation_id == "v-forced"
        assert other_result is not None
        assert other_result.variation_id == "v-other"
        # The preview context leaves no trace of its own...
        assert preview_writes == []
        # ...while the plain context persists and tracks exactly as it always has.
        assert other_writes != []
        assert len(mock_tracking_endpoint.calls) > 0
    finally:
        core.close()


# --- AC10: non-preview flows are entirely unchanged ---------------------------


def test_non_preview_context_tracking_and_persistence_unchanged(
    respx_mock, mock_tracking_endpoint
) -> None:
    """A regression lock: a context that never calls ``set_preview`` must keep
    tracking and persisting exactly as before -- this file's new suppression
    gate must be conditioned on preview state, never a blanket change to the
    normal path.
    """
    spy_store = _SpyDataStore()
    core = _build_core(respx_mock, _preview_config(), spy_store)
    try:
        ctx = core.create_context("visitor-normal-regression")

        result = ctx.run_experience("other-key", enable_tracking=True)
        ctx.set_attributes({"tier": "gold"})
        conversion = ctx.track_conversion("purchase_completed")

        core.flush()

        assert result is not None
        assert result.variation_id == "v-other"
        assert conversion.tracked is True
        assert spy_store.set_calls != []
        assert len(mock_tracking_endpoint.calls) > 0
    finally:
        core.close()
