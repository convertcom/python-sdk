"""Integration: custom adapter substitution preserves SDK semantics (Story 4.4).

Story 4.4 ratifies the *public extension boundaries* the architecture has
reserved since Epic 1 (FR6 / FR44 / NFR16-NFR19). The extension INFRASTRUCTURE
(the ``Transport`` / ``DataStore`` Protocols, the ``HttpxTransport`` /
``InMemoryDataStore`` defaults, and the two injection points on ``Core`` /
``SDKConfig``) was shipped by Stories 1.x-3.x. This module is the behavioral
proof that the boundaries actually work: a caller-supplied, duck-typed adapter
substituted for a default produces semantically identical evaluation, tracking,
and queue-flush behavior, with byte-identical evaluation determinism.

The shipped injection contract is a HYBRID (verified against the on-disk code,
which is authoritative over the mangled story prose):

* **Transport** is a keyword-only argument on ``Core``::

      Core(config, transport=my_transport)

  When omitted (and an ``sdk_key`` is configured) ``Core`` lazily constructs the
  default ``HttpxTransport``; direct-config init never touches a transport.

* **Storage** is a FIELD on ``SDKConfig``::

      SDKConfig(..., data_store=my_store)

  ``Core`` reads ``config.data_store`` and falls back to a fresh
  ``InMemoryDataStore`` when it is ``None``.

Adapter validation is duck-typed via ``typing.Protocol`` (both Protocols are
``@runtime_checkable``); a structurally-correct adapter is accepted without
subclassing and without depending on the concrete default (AC #2 / #3). The
stub adapters below are defined INLINE and are never shipped as runtime code
(Story 4.4 Testing Requirements).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from convert_sdk.adapters.storage.in_memory import InMemoryDataStore
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig
from convert_sdk.core import Core
from convert_sdk.ports.storage import DataStore
from convert_sdk.ports.transport import Transport

# A representative config carrying one experience (``e1`` / ``exp-one``) and the
# goals tracking exercises. Inlined (rather than read from the fixture file) so
# the determinism comparison is anchored to an immutable literal — the parity
# guard must not silently drift if a shared fixture changes.
_CONFIG: Dict[str, Any] = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {
            "id": "e1",
            "key": "exp-one",
            "type": "a/b",
            "status": "running",
            "traffic_allocation": 100.0,
            "variations": [
                {"id": "v1", "key": "control", "traffic_allocation": 50.0},
                {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
            ],
        }
    ],
    "features": [],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "audiences": [],
    "segments": [],
}


# --- inline stub adapters (NEVER shipped as runtime code) -------------------


class RecordingTransport:
    """A duck-typed :class:`~convert_sdk.ports.transport.Transport` substitute.

    Structurally satisfies the ``Transport`` protocol (``fetch_config`` /
    ``send_tracking`` / ``close`` / context-manager) WITHOUT importing or
    subclassing ``HttpxTransport`` — proving the SDK never depends on the
    concrete default when a custom transport is supplied (AC #2). It performs no
    network I/O: ``fetch_config`` returns the in-test config literal and
    ``send_tracking`` records each delivered batch so the test can assert
    queue-flush semantics are preserved.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = config
        self.fetch_calls = 0
        self.deliveries: List[Tuple[Dict[str, Any], str]] = []
        self.closed = False

    def fetch_config(self, config: "SDKConfig") -> Dict[str, Any]:
        self.fetch_calls += 1
        return self._config

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> int:
        self.deliveries.append((payload, sdk_key))
        return 200

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "RecordingTransport":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


class RecordingDataStore:
    """A duck-typed :class:`~convert_sdk.ports.storage.DataStore` substitute.

    Structurally satisfies the frozen four-method ``DataStore`` surface
    (``get`` / ``set`` / ``has`` / ``delete``) WITHOUT subclassing or importing
    ``InMemoryDataStore`` (AC #2 / Critical Warning #4 — ``typing.Protocol``
    only, no ABC). Wraps a plain dict and records every operation so the test
    can prove the SDK routes visitor-linked state (sticky context state and
    goal-dedup markers) through the supplied store rather than the default.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self.ops: List[Tuple[str, str]] = []

    def get(self, key: str) -> Any:
        self.ops.append(("get", key))
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.ops.append(("set", key))
        self._store[key] = value

    def has(self, key: str) -> bool:
        self.ops.append(("has", key))
        return key in self._store

    def delete(self, key: str) -> None:
        self.ops.append(("delete", key))
        self._store.pop(key, None)


# --- protocol conformance (AC #2 / #3) --------------------------------------


def test_stub_adapters_structurally_satisfy_the_runtime_checkable_protocols():
    # The boundaries are @runtime_checkable, so a duck-typed adapter that never
    # subclasses the default is recognized as the protocol type — this is the
    # mechanism AC #2/#3 rely on (the SDK depends on the Protocol, not the
    # concrete default).
    assert isinstance(RecordingTransport(_CONFIG), Transport)
    assert isinstance(RecordingDataStore(), DataStore)
    # And neither stub inherits from the concrete default implementation.
    assert not isinstance(RecordingTransport(_CONFIG), HttpxTransport)
    assert not isinstance(RecordingDataStore(), InMemoryDataStore)


# --- Task 4.1: custom transport replaces HttpxTransport end-to-end ----------


def test_custom_transport_replaces_httpx_end_to_end_preserving_semantics():
    transport = RecordingTransport(_CONFIG)
    core = Core(SDKConfig(sdk_key="k"), transport=transport).initialize()
    try:
        # fetch_config went through the custom transport — no network, no
        # HttpxTransport ever constructed.
        assert transport.fetch_calls == 1
        assert core.is_ready
        assert core._transport is transport  # custom adapter, not a default
        assert core._owns_transport is False

        ctx = core.create_context("visitor-1")
        # Evaluation still works against the snapshot fetched via the custom
        # transport (semantics unchanged).
        results = ctx.run_experiences()
        assert [r.experience_key for r in results] == ["exp-one"]

        # Tracking enqueues with no delivery until an explicit flush (queue
        # semantics preserved).
        ctx.track_conversion("purchase_completed")
        assert transport.deliveries == []

        core.flush()
        # Exactly one batch delivered through the custom transport's
        # send_tracking, carrying the tracked goal.
        assert len(transport.deliveries) == 1
        payload, sdk_key = transport.deliveries[0]
        assert sdk_key == "k"
        events = payload["visitors"][0]["events"]
        # Story 2.5: run_experiences() enqueues a bucketing event before the
        # conversion event, so find the conversion event by eventType rather
        # than assuming position 0.
        conversion_events = [e for e in events if e.get("eventType") == "conversion"]
        assert len(conversion_events) == 1
        assert conversion_events[0]["data"]["goalId"] == "g1"

        # A second flush on the now-empty queue is a safe no-op (no extra
        # delivery) — queue-release semantics unchanged.
        core.flush()
        assert len(transport.deliveries) == 1
    finally:
        core.close()


# --- Task 4.2: custom storage replaces InMemoryDataStore for sticky state ---


def test_custom_storage_replaces_in_memory_default_for_sticky_bucketing():
    transport = RecordingTransport(_CONFIG)
    store = RecordingDataStore()
    core = Core(
        SDKConfig(sdk_key="k", data_store=store),
        transport=transport,
    ).initialize()
    try:
        # The supplied store is the one Core uses — no fallback to the default.
        assert core._data_store is store
        assert not isinstance(core._data_store, InMemoryDataStore)

        # Persist sticky per-visitor context state through the custom store, then
        # rehydrate it on a fresh context for the same visitor (sticky semantics
        # preserved across the supplied boundary).
        ctx = core.create_context("visitor-1")
        ctx.set_attributes({"plan": "pro"})

        # The write landed in the custom store (a state:* key was set).
        assert any(op == "set" and key.startswith("state:") for op, key in store.ops)

        rehydrated = core.create_context("visitor-1")
        assert rehydrated.attributes.get("plan") == "pro"

        # Goal-dedup markers also route through the custom store: a default-mode
        # duplicate conversion is deduplicated via the supplied store's has/set.
        first = ctx.track_conversion("purchase_completed")
        second = ctx.track_conversion("purchase_completed")
        assert first.tracked is True
        assert second.tracked is False  # deduplicated through the custom store
        assert second.reason == "deduplicated"
        assert any(op == "set" and "dedup" in key for op, key in store.ops)
    finally:
        core.close()


# --- Task 4.4: evaluation determinism is byte-identical to the default run --


def _evaluation_signature(core: Core, visitor_id: str):
    """A comparable, order-stable signature of a visitor's evaluation results.

    ``ExperienceResult`` is a frozen dataclass, so equality is structural; the
    signature captures every field the parity guard cares about (experience,
    variation, bucketing) without depending on adapter identity.
    """
    ctx = core.create_context(visitor_id)
    return tuple(
        (r.experience_id, r.experience_key, r.variation_id, r.variation_key)
        for r in ctx.run_experiences()
    )


@pytest.mark.parametrize("visitor_id", ["visitor-1", "visitor-42", "用户123", "v-zzz"])
def test_evaluation_is_byte_identical_between_default_and_custom_adapters(visitor_id):
    # Default-adapter run: direct config (no transport), default in-memory store.
    default_core = Core(SDKConfig(data=_CONFIG)).initialize()
    try:
        default_sig = _evaluation_signature(default_core, visitor_id)
    finally:
        default_core.close()

    # Custom-adapter run: custom transport + custom store, same snapshot.
    custom_core = Core(
        SDKConfig(sdk_key="k", data_store=RecordingDataStore()),
        transport=RecordingTransport(_CONFIG),
    ).initialize()
    try:
        custom_sig = _evaluation_signature(custom_core, visitor_id)
    finally:
        custom_core.close()

    # Substituting adapters must not perturb deterministic bucketing in any way
    # (NFR16-NFR19, Critical Warning #5).
    assert custom_sig == default_sig
    # And the visitor actually buckets into the experience (guard against the
    # vacuous "both empty" pass).
    assert default_sig and default_sig[0][1] == "exp-one"
