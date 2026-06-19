"""Story 2.5 — bucketing activation-event tracking tests (RED phase).

Proves the acceptance criteria for the additive bucketing-event feature:

AC#1 — ``build_bucketing_payload`` emits the EXACT wire shape
        ``{"eventType": "bucketing", "data": {"experienceId": <str>, "variationId": <str>}}``
        (no timestamp, no extra keys), inside the full JS-SDK envelope; bucketing +
        conversion events for the SAME visitor are batched into ONE visitors[] entry
        when both are flushed through the Tracker.

AC#2 — ``run_experience(..., enable_tracking=False)`` enqueues NO bucketing event while
        the returned ExperienceResult is identical to the ``enable_tracking=True`` (default)
        call; ``enable_tracking=True`` enqueues exactly one; ``enable_tracking`` is a
        keyword-only parameter that defaults to True.

AC#3 — Deduplication: two ``run_experience(key)`` calls for the same visitor+experience
        enqueue ONE bucketing event; ``run_experiences()`` re-evaluation emits at most one
        per (visitor, experience).

AC#4 — No-Tracker: a directly-constructed ``Context`` (no tracker) buckets a visitor with
        NO error and NO enqueue; the return value is unchanged.

AC#5 — EventBus: a registered ``LifecycleEvent.BUCKETING`` handler receives a
        ``BucketingEventPayload`` with the right ids; a raising handler does not break
        the tracking flow.

Fixture strategy (SonarCloud new_duplicated_lines_density ≤ 3% guard):
- ``_CONFIG``: single shared CONFIG that reliably buckets a visitor into a
  variation in the unrestricted experience.  Same fixture shape used by
  ``tests/test_experience_evaluation.py`` — reused verbatim so tests stay orthogonal.
- ``tracker`` / ``tracker_with_bus`` fixtures: shared factory yielding a Tracker
  wired with FakeTransport + optional InProcessEventBus.
- ``assert_bucketing_wire_event``: shared assertion so no two test bodies duplicate
  the wire-shape check.
"""

from __future__ import annotations

import pytest

from convert_sdk import InMemoryDataStore
from convert_sdk.adapters.events.in_process import InProcessEventBus
from convert_sdk.config import SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.errors import TrackingDeliveryError
from convert_sdk.events import LifecycleEvent
from convert_sdk.tracking.tracker import Tracker

# --- New symbols that don't exist yet (RED phase) ---------------------------
# These imports will fail with ImportError when the production code is absent,
# causing the test *function* bodies to raise rather than the collection to error.
# We import them lazily inside a small helper so pytest can collect all test
# items; each test that calls the helper will fail with the expected ImportError.

def _import_new_symbols():
    """Lazy import of Story 2.5 symbols that do not exist yet.

    Returns a namespace dict with keys: BucketingEventPayload, BucketingEvent,
    build_bucketing_payload, bucketing_marker_key, evaluate_bucketing_dedup.
    Raises ImportError when the production code is absent (RED phase).
    """
    from convert_sdk.domain.results import BucketingEvent
    from convert_sdk.events import BucketingEventPayload
    from convert_sdk.tracking.deduplication import (
        bucketing_marker_key,
        evaluate_bucketing_dedup,
    )
    from convert_sdk.tracking.payloads import build_bucketing_payload
    return {
        "BucketingEventPayload": BucketingEventPayload,
        "BucketingEvent": BucketingEvent,
        "build_bucketing_payload": build_bucketing_payload,
        "bucketing_marker_key": bucketing_marker_key,
        "evaluate_bucketing_dedup": evaluate_bucketing_dedup,
    }


# ---------------------------------------------------------------------------
# Shared fixture config (unrestricted — every visitor buckets in)
# ---------------------------------------------------------------------------

_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {
            "id": "e1",
            "key": "unrestricted",
            "variations": [
                {"id": "v1", "key": "control", "traffic_allocation": 50.0},
                {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
            ],
        }
    ],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
    "audiences": [],
    "segments": [],
}


# ---------------------------------------------------------------------------
# Shared helpers / factories
# ---------------------------------------------------------------------------


class FakeTransport:
    """Captures tracking POSTs without network I/O (mirrors test_tracker.py)."""

    def __init__(self) -> None:
        self.calls = []
        self.fail = False

    def fetch_config(self, config):  # pragma: no cover
        return {}

    def send_tracking(self, payload, *, sdk_key):
        if self.fail:
            raise TrackingDeliveryError("boom")
        self.calls.append({"payload": payload, "sdk_key": sdk_key})
        return 200

    def close(self):  # pragma: no cover
        pass


@pytest.fixture()
def snapshot():
    """Immutable config snapshot from the shared bucketing config."""
    return load_snapshot(_CONFIG)


@pytest.fixture()
def store():
    """A fresh InMemoryDataStore per test."""
    return InMemoryDataStore()


@pytest.fixture()
def transport():
    """A fresh FakeTransport per test."""
    return FakeTransport()


@pytest.fixture()
def tracker(snapshot, store, transport):
    """Tracker wired with the shared snapshot, store, and FakeTransport (no bus)."""
    cfg = SDKConfig(sdk_key="my-sdk-key")
    return Tracker(
        snapshot=snapshot,
        config=cfg,
        transport=transport,
        data_store=store,
    )


@pytest.fixture()
def bus():
    """A fresh InProcessEventBus per test."""
    return InProcessEventBus()


@pytest.fixture()
def tracker_with_bus(snapshot, store, transport, bus):
    """Tracker wired with InProcessEventBus for lifecycle-event tests."""
    cfg = SDKConfig(sdk_key="my-sdk-key")
    return Tracker(
        snapshot=snapshot,
        config=cfg,
        transport=transport,
        data_store=store,
        event_bus=bus,
    )


def _wired_core_context(visitor_id: str, tracker_inst, snapshot_inst) -> Context:
    """Return a Context linked to the given tracker (simulates Core.create_context)."""
    return Context(
        visitor_id,
        snapshot_inst,
        tracker=tracker_inst,
    )


def assert_bucketing_wire_event(event: dict, experience_id: str, variation_id: str) -> None:
    """Assert the bucketing event dict matches the EXACT wire contract.

    Wire shape (architecture.md §"Bucketing Event Tracking Format"):
        {"eventType": "bucketing", "data": {"experienceId": <str>, "variationId": <str>}}

    Invariants:
    - No ``timestamp`` key.
    - No extra keys beyond ``eventType`` and ``data``.
    - ``data`` has EXACTLY ``experienceId`` and ``variationId`` (string values).
    """
    assert event["eventType"] == "bucketing"
    assert set(event.keys()) == {"eventType", "data"}, (
        f"Unexpected wire keys: {set(event.keys())}"
    )
    data = event["data"]
    assert set(data.keys()) == {"experienceId", "variationId"}, (
        f"Unexpected data keys: {set(data.keys())}"
    )
    assert data["experienceId"] == str(experience_id)
    assert data["variationId"] == str(variation_id)
    assert "timestamp" not in event
    assert "timestamp" not in data


# ---------------------------------------------------------------------------
# AC#1 — build_bucketing_payload wire shape
# ---------------------------------------------------------------------------


class TestBuildBucketingPayload:
    """AC#1: ``build_bucketing_payload`` emits the exact wire shape."""

    def test_event_type_is_bucketing(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v1"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        wire_event = payload["visitors"][0]["events"][0]
        assert wire_event["eventType"] == "bucketing"

    def test_data_has_experience_id_and_variation_id_only(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v2"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        wire_event = payload["visitors"][0]["events"][0]
        assert_bucketing_wire_event(wire_event, "e1", "v2")

    def test_no_timestamp_on_event(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v1"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        wire_event = payload["visitors"][0]["events"][0]
        assert "timestamp" not in wire_event

    def test_envelope_matches_js_sdk_fields(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v1"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        assert payload["accountId"] == "100123"
        assert payload["projectId"] == "200456"
        assert payload["source"] == "js-sdk"
        assert isinstance(payload["enrichData"], bool)

    def test_enrich_data_computed_from_data_store_presence(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v1"
        )
        assert ns["build_bucketing_payload"](snapshot, event, data_store=None)["enrichData"] is True
        sentinel = object()
        assert (
            ns["build_bucketing_payload"](snapshot, event, data_store=sentinel)["enrichData"]
            is False
        )

    def test_visitor_id_on_wire(self, snapshot):
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="visitor-xyz", experience_id="e1", variation_id="v1"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        assert payload["visitors"][0]["visitorId"] == "visitor-xyz"

    def test_experience_id_and_variation_id_are_strings_on_wire(self, snapshot):
        """variationId / experienceId on the wire are STRINGS (JS .toString() parity)."""
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v1"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        data = payload["visitors"][0]["events"][0]["data"]
        assert isinstance(data["experienceId"], str)
        assert isinstance(data["variationId"], str)

    def test_payload_is_json_serializable(self, snapshot):
        import json
        ns = _import_new_symbols()
        event = ns["BucketingEvent"](
            visitor_id="v1", experience_id="e1", variation_id="v2"
        )
        payload = ns["build_bucketing_payload"](snapshot, event)
        assert json.loads(json.dumps(payload)) == payload

    def test_bucketing_and_conversion_events_batched_in_one_visitor_entry(
        self, snapshot, store, transport
    ):
        """Bucketing + conversion events for the SAME visitor serialize into ONE
        visitors[] entry when both are flushed through the Tracker (AC#1 batching)."""
        cfg = SDKConfig(sdk_key="sk")
        t = Tracker(
            snapshot=snapshot,
            config=cfg,
            transport=transport,
            data_store=store,
        )
        ctx = _wired_core_context("visitor-batch", t, snapshot)
        # run_experience enqueues a bucketing event (enable_tracking=True by default).
        result = ctx.run_experience("unrestricted")
        assert result is not None
        # Also enqueue a conversion event for the same visitor.
        t.track(visitor_id="visitor-batch", goal_key="purchase_completed")
        t.flush()

        assert len(transport.calls) == 1
        visitors = transport.calls[0]["payload"]["visitors"]
        # Both events must share ONE visitors[] entry.
        assert len(visitors) == 1
        assert visitors[0]["visitorId"] == "visitor-batch"
        event_types = {e["eventType"] for e in visitors[0]["events"]}
        assert "bucketing" in event_types
        assert "conversion" in event_types


# ---------------------------------------------------------------------------
# AC#2 — enable_tracking parameter on run_experience / run_experiences
# ---------------------------------------------------------------------------


class TestEnableTrackingParameter:
    """AC#2: ``enable_tracking`` is keyword-only, defaults True, gates enqueueing."""

    def test_enable_tracking_defaults_true_enqueues_one_event(
        self, snapshot, tracker
    ):
        """Default (enable_tracking=True) enqueues exactly one bucketing event."""
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        result = ctx.run_experience("unrestricted")
        assert result is not None
        assert tracker._queue.length == 1

    def test_enable_tracking_false_enqueues_no_event(self, snapshot, tracker):
        """enable_tracking=False must enqueue NO bucketing event."""
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        result = ctx.run_experience("unrestricted", enable_tracking=False)
        assert result is not None
        assert tracker._queue.length == 0

    def test_enable_tracking_false_returns_identical_experience_result(
        self, snapshot
    ):
        """The ExperienceResult must be byte-for-byte identical regardless of
        enable_tracking — the parameter gates tracking only, not evaluation."""
        cfg = SDKConfig(sdk_key="sk")
        tracker_a = Tracker(
            snapshot=snapshot,
            config=cfg,
            transport=FakeTransport(),
            data_store=InMemoryDataStore(),
        )
        tracker_b = Tracker(
            snapshot=snapshot,
            config=cfg,
            transport=FakeTransport(),
            data_store=InMemoryDataStore(),
        )
        ctx_a = _wired_core_context("visitor-42", tracker_a, snapshot)
        ctx_b = _wired_core_context("visitor-42", tracker_b, snapshot)

        result_with = ctx_a.run_experience("unrestricted", enable_tracking=True)
        result_without = ctx_b.run_experience("unrestricted", enable_tracking=False)

        assert result_with is not None and result_without is not None
        assert result_with.experience_key == result_without.experience_key
        assert result_with.variation_id == result_without.variation_id
        assert result_with.experience_id == result_without.experience_id

    def test_enable_tracking_positional_raises_type_error(self, snapshot, tracker):
        """``enable_tracking`` must be keyword-only — passing it positionally raises TypeError."""
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        with pytest.raises(TypeError):
            ctx.run_experience("unrestricted", None, None, True)  # type: ignore[call-arg]

    def test_run_experiences_enable_tracking_false_enqueues_nothing(
        self, snapshot, tracker
    ):
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        results = ctx.run_experiences(enable_tracking=False)
        assert isinstance(results, list)
        assert tracker._queue.length == 0

    def test_run_experiences_enable_tracking_true_enqueues_events(
        self, snapshot, tracker
    ):
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        results = ctx.run_experiences(enable_tracking=True)
        # All experiences that bucket must enqueue a bucketing event.
        assert tracker._queue.length == len(results)


# ---------------------------------------------------------------------------
# AC#3 — deduplication (bucketing_marker_key + evaluate_bucketing_dedup)
# ---------------------------------------------------------------------------


class TestBucketingDeduplication:
    """AC#3: bucketing dedup functions and per-(visitor, experience) suppression."""

    def test_bucketing_marker_key_is_visitor_and_experience_scoped(self):
        ns = _import_new_symbols()
        k1 = ns["bucketing_marker_key"]("v1", "e1")
        k2 = ns["bucketing_marker_key"]("v1", "e2")
        k3 = ns["bucketing_marker_key"]("v2", "e1")
        assert k1 != k2 and k1 != k3 and k2 != k3

    def test_bucketing_marker_key_prefixed_with_bucketing(self):
        ns = _import_new_symbols()
        key = ns["bucketing_marker_key"]("v1", "e1")
        assert key.startswith("bucketing:")

    def test_bucketing_marker_key_collision_safe(self):
        ns = _import_new_symbols()
        assert (
            ns["bucketing_marker_key"]("a:b", "c") != ns["bucketing_marker_key"]("a", "b:c")
        )

    def test_evaluate_bucketing_dedup_first_time_returns_true(self, store):
        """First call with a fresh store returns True (should enqueue)."""
        ns = _import_new_symbols()
        should_enqueue = ns["evaluate_bucketing_dedup"](
            store, visitor_id="v1", experience_id="e1"
        )
        assert should_enqueue is True

    def test_evaluate_bucketing_dedup_persists_marker_on_first_time(self, store):
        ns = _import_new_symbols()
        ns["evaluate_bucketing_dedup"](store, visitor_id="v1", experience_id="e1")
        assert store.has(ns["bucketing_marker_key"]("v1", "e1")) is True

    def test_evaluate_bucketing_dedup_second_time_returns_false(self, store):
        ns = _import_new_symbols()
        ns["evaluate_bucketing_dedup"](store, visitor_id="v1", experience_id="e1")
        should_enqueue = ns["evaluate_bucketing_dedup"](
            store, visitor_id="v1", experience_id="e1"
        )
        assert should_enqueue is False

    def test_run_experience_twice_enqueues_only_one_bucketing_event(
        self, snapshot, tracker
    ):
        """Two run_experience calls for the same visitor+experience enqueue ONE event."""
        ctx = _wired_core_context("visitor-dedup", tracker, snapshot)
        ctx.run_experience("unrestricted")
        ctx.run_experience("unrestricted")
        assert tracker._queue.length == 1

    def test_run_experiences_does_not_double_enqueue_same_experience(
        self, snapshot, tracker
    ):
        """run_experiences() called twice emits at most one bucketing event per
        (visitor, experience)."""
        ctx = _wired_core_context("visitor-dedup", tracker, snapshot)
        ctx.run_experiences()
        ctx.run_experiences()
        # The config has one experience; at most one bucketing event per pair.
        assert tracker._queue.length <= 1


# ---------------------------------------------------------------------------
# AC#4 — no-Tracker Context (direct construction)
# ---------------------------------------------------------------------------


class TestNoTrackerContext:
    """AC#4: directly-constructed Context (no tracker) — no error, no enqueue."""

    def test_run_experience_without_tracker_returns_result(self, snapshot):
        ctx = Context("visitor-1", snapshot)
        result = ctx.run_experience("unrestricted")
        assert isinstance(result, ExperienceResult)

    def test_run_experience_without_tracker_does_not_raise(self, snapshot):
        ctx = Context("visitor-1", snapshot)
        ctx.run_experience("unrestricted")  # must not raise

    def test_run_experience_without_tracker_no_queue_side_effects(self, snapshot):
        """No Tracker -> no queue, no transport call — safe no-op."""
        ctx = Context("visitor-1", snapshot)
        ctx.run_experience("unrestricted")
        # No tracker -> no side effects to assert against; test passes if no raise.

    def test_run_experience_without_tracker_result_identical_to_with_tracker(
        self, snapshot, tracker
    ):
        """Return value must be identical whether or not a tracker is present."""
        ctx_no_tracker = Context("visitor-99", snapshot)
        ctx_with_tracker = _wired_core_context("visitor-99", tracker, snapshot)

        result_no = ctx_no_tracker.run_experience("unrestricted")
        result_with = ctx_with_tracker.run_experience("unrestricted")

        assert result_no is not None and result_with is not None
        assert result_no.variation_id == result_with.variation_id
        assert result_no.experience_key == result_with.experience_key


# ---------------------------------------------------------------------------
# AC#5 — EventBus: BUCKETING lifecycle event emission
# ---------------------------------------------------------------------------


class TestBucketingLifecycleEvent:
    """AC#5: LifecycleEvent.BUCKETING fired with BucketingEventPayload; raising handler
    does not break the tracking flow."""

    def test_bucketing_event_emitted_with_correct_payload(
        self, snapshot, tracker_with_bus, bus
    ):
        ns = _import_new_symbols()
        received = []
        bus.on(LifecycleEvent.BUCKETING, lambda p, error=None: received.append(p))

        ctx = _wired_core_context("visitor-event", tracker_with_bus, snapshot)
        result = ctx.run_experience("unrestricted")
        assert result is not None

        assert len(received) == 1
        payload = received[0]
        assert isinstance(payload, ns["BucketingEventPayload"])
        assert payload.visitor_id == "visitor-event"
        assert payload.experience_id == result.experience_id
        assert payload.variation_id == result.variation_id

    def test_bucketing_event_not_emitted_when_enable_tracking_false(
        self, snapshot, tracker_with_bus, bus
    ):
        received = []
        bus.on(LifecycleEvent.BUCKETING, lambda p, error=None: received.append(p))

        ctx = _wired_core_context("visitor-event", tracker_with_bus, snapshot)
        ctx.run_experience("unrestricted", enable_tracking=False)

        assert received == []

    def test_bucketing_event_not_emitted_when_no_bus(self, snapshot, tracker):
        """No event bus -> emission is a no-op; no error raised."""
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        ctx.run_experience("unrestricted")  # must not raise

    def test_raising_handler_does_not_break_tracking_flow(
        self, snapshot, tracker_with_bus, bus
    ):
        """A handler that raises must NOT prevent the bucketing event from being
        enqueued or the tracking flow from completing normally."""

        def bad_handler(payload, error=None):
            raise RuntimeError("handler exploded")

        bus.on(LifecycleEvent.BUCKETING, bad_handler)

        ctx = _wired_core_context("visitor-raise", tracker_with_bus, snapshot)
        result = ctx.run_experience("unrestricted")
        assert result is not None
        # The bucketing event must still have been enqueued despite the bad handler.
        assert tracker_with_bus._queue.length == 1

    def test_bucketing_event_not_emitted_on_miss(
        self, snapshot, tracker_with_bus, bus
    ):
        """No bucketing event when run_experience returns None (no variation selected)."""
        received = []
        bus.on(LifecycleEvent.BUCKETING, lambda p, error=None: received.append(p))

        ctx = _wired_core_context("visitor-1", tracker_with_bus, snapshot)
        result = ctx.run_experience("nonexistent-experience")
        assert result is None
        assert received == []

    def test_bucketing_event_deduped_only_fired_once(
        self, snapshot, tracker_with_bus, bus
    ):
        """BUCKETING lifecycle event fires at most once per (visitor, experience) —
        dedup suppresses the second enqueue and thus the second emission."""
        received = []
        bus.on(LifecycleEvent.BUCKETING, lambda p, error=None: received.append(p))

        ctx = _wired_core_context("visitor-dedup2", tracker_with_bus, snapshot)
        ctx.run_experience("unrestricted")
        ctx.run_experience("unrestricted")  # deduped — no second emit

        assert len(received) == 1


# ---------------------------------------------------------------------------
# AC#1 continuation — flush wire payload integration assertion
# ---------------------------------------------------------------------------


class TestBucketingPayloadOnFlush:
    """Assert the flushed payload contains the correct bucketing wire event."""

    def test_flushed_payload_contains_bucketing_event_with_correct_shape(
        self, snapshot, tracker, transport
    ):
        ctx = _wired_core_context("visitor-flush", tracker, snapshot)
        result = ctx.run_experience("unrestricted")
        assert result is not None
        tracker.flush()

        assert len(transport.calls) == 1
        visitors = transport.calls[0]["payload"]["visitors"]
        assert len(visitors) == 1
        events = visitors[0]["events"]
        bucketing_events = [e for e in events if e["eventType"] == "bucketing"]
        assert len(bucketing_events) == 1
        assert_bucketing_wire_event(
            bucketing_events[0], result.experience_id, result.variation_id
        )

    def test_flush_empty_queue_after_enable_tracking_false_is_noop(
        self, snapshot, tracker, transport
    ):
        ctx = _wired_core_context("visitor-1", tracker, snapshot)
        ctx.run_experience("unrestricted", enable_tracking=False)
        tracker.flush()
        assert transport.calls == []
