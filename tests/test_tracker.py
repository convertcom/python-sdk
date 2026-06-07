"""Story 2.3 — tracker orchestration unit tests (BE-3).

Proves the ``tracking/tracker.py`` seam between Context, dedup, queue, and the
transport boundary, using a fake transport (unit layer — RESPX integration
coverage lives in ``tests/integration/`` per qs-06).

* Flush serializes batched per-visitor events through the Story 2.2
  ``tracking/payloads.py`` builder (NO second serializer).
* Flush delivers through the ``Transport`` port and clears the queue on success.
* Empty-queue flush is a safe no-op (no transport call, no error).
* Batch-size release funnels through the same single release path as explicit
  flush.
"""

from typing import Any, Dict, List

from convert_sdk.config import SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ConversionStatus
from convert_sdk.tracking.tracker import Tracker


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [],
    "features": [],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "audiences": [],
    "segments": [],
}


class FakeTransport:
    """Captures tracking POSTs without touching the network."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.fail = False

    def fetch_config(self, config):  # pragma: no cover - unused here
        return {}

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> None:
        if self.fail:
            from convert_sdk.errors import TrackingDeliveryError

            raise TrackingDeliveryError("boom")
        self.calls.append({"payload": payload, "sdk_key": sdk_key})

    def close(self) -> None:  # pragma: no cover - unused here
        pass


def _tracker(transport=None, batch_size=10):
    snap = load_snapshot(CONFIG)
    cfg = SDKConfig(sdk_key="my-sdk-key", batch_size=batch_size)
    return Tracker(snapshot=snap, config=cfg, transport=transport)


def test_flush_empty_queue_is_noop():
    transport = FakeTransport()
    tracker = _tracker(transport)
    tracker.flush()
    assert transport.calls == []


def test_flush_serializes_via_payloads_and_delivers_and_clears():
    transport = FakeTransport()
    tracker = _tracker(transport)
    tracker.track(visitor_id="v1", goal_key="purchase_completed", revenue=12.5)
    tracker.flush()

    assert len(transport.calls) == 1
    payload = transport.calls[0]["payload"]
    # Story 2.2 envelope shape (verbose JS-SDK wire names).
    assert payload["accountId"] == "100123"
    assert payload["projectId"] == "200456"
    assert payload["source"] == "js-sdk"
    assert payload["visitors"][0]["visitorId"] == "v1"
    event = payload["visitors"][0]["events"][0]
    assert event["eventType"] == "conversion"
    assert event["data"]["goalId"] == "g1"
    # revenue mapped to goalData amount entry by the Story 2.2 serializer.
    assert {"key": "amount", "value": 12.5} in event["data"]["goalData"]
    assert transport.calls[0]["sdk_key"] == "my-sdk-key"

    # Queue cleared after a successful flush -> a second flush is a no-op.
    tracker.flush()
    assert len(transport.calls) == 1


def test_flush_groups_multiple_visitors_in_one_batch():
    transport = FakeTransport()
    tracker = _tracker(transport)
    tracker.track(visitor_id="v1", goal_key="purchase_completed")
    tracker.track(visitor_id="v2", goal_key="signup")
    tracker.flush()
    assert len(transport.calls) == 1
    visitors = transport.calls[0]["payload"]["visitors"]
    assert {v["visitorId"] for v in visitors} == {"v1", "v2"}


def test_batch_size_release_funnels_through_shared_path():
    transport = FakeTransport()
    tracker = _tracker(transport, batch_size=2)
    tracker.track(visitor_id="v1", goal_key="purchase_completed")
    # Second distinct goal reaches batch_size -> auto release via shared path.
    tracker.track(visitor_id="v1", goal_key="signup")
    assert len(transport.calls) == 1
    # Queue cleared by the auto release.
    tracker.flush()
    assert len(transport.calls) == 1


def test_failed_delivery_restores_queue():
    transport = FakeTransport()
    transport.fail = True
    tracker = _tracker(transport)
    tracker.track(visitor_id="v1", goal_key="purchase_completed")
    # Flush should surface the delivery error; the queue must not be silently lost.
    try:
        tracker.flush()
    except Exception:
        pass
    transport.fail = False
    tracker.flush()
    # The originally-queued event was preserved and delivered on retry.
    assert len(transport.calls) == 1


def test_track_returns_dedup_outcome():
    transport = FakeTransport()
    tracker = _tracker(transport)
    first = tracker.track(visitor_id="v1", goal_key="purchase_completed")
    assert first.status is ConversionStatus.QUEUED
    second = tracker.track(visitor_id="v1", goal_key="purchase_completed")
    assert second.status is ConversionStatus.DEDUPLICATED
