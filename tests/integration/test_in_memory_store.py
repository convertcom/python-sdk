"""Story 3.1 — qs-06 integration coverage for the in-memory persistence boundary.

Exercises the ``DataStore`` boundary through the public SDK surface using the
SHARED qs-06 ``in_memory_store`` fixture from ``tests/integration/conftest.py``
(no hand-rolled fixtures; fully offline). Proves:

* the default ``InMemoryDataStore`` supports the full four-method protocol
  end-to-end through the public import surface;
* ``Core`` honors an injected ``DataStore`` (NFR19 swappability) — the dedup
  marker lands in the injected store, proving the core depends on the protocol,
  not the concrete class;
* ``isinstance(stub, DataStore)`` holds for a duck-typed adapter
  (``@runtime_checkable``).
"""

from __future__ import annotations

from convert_sdk import Core, DataStore, InMemoryDataStore
from convert_sdk.config import SDKConfig


_DIRECT_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
    "audiences": [],
    "segments": [],
}


def test_shared_fixture_provides_in_memory_store(in_memory_store):
    assert isinstance(in_memory_store, InMemoryDataStore)
    assert isinstance(in_memory_store, DataStore)


def test_store_protocol_round_trip_through_shared_fixture(in_memory_store):
    in_memory_store.set("k", {"x": 1})
    assert in_memory_store.get("k") == {"x": 1}
    assert in_memory_store.has("k") is True
    in_memory_store.delete("k")
    assert in_memory_store.has("k") is False
    assert in_memory_store.get("k") is None
    # Idempotent delete.
    in_memory_store.delete("k")


def test_core_routes_dedup_state_through_injected_store(in_memory_store):
    # NFR19: an externally supplied DataStore is the one Core uses for dedup,
    # without any change to evaluation/tracking semantics.
    config = SDKConfig(data=_DIRECT_CONFIG, data_store=in_memory_store)
    core = Core(config).initialize()
    try:
        ctx = core.create_context("visitor-42")
        first = ctx.track_conversion("purchase_completed")
        assert first.tracked is True
        # Marker observable through the injected store.
        assert any(k.startswith("dedup:") for k in _injected_keys(in_memory_store))
        # A default repeat is deduplicated (truth-table unchanged after migration).
        second = ctx.track_conversion("purchase_completed")
        assert second.tracked is False
        assert second.reason == "deduplicated"
    finally:
        core.close()


def test_core_uses_duck_typed_store_via_sdkconfig():
    class _Stub:
        def __init__(self) -> None:
            self._d: dict = {}

        def get(self, key):
            return self._d.get(key)

        def set(self, key, value, ttl=None):
            self._d[key] = value

        def has(self, key):
            return key in self._d

        def delete(self, key):
            self._d.pop(key, None)

    stub = _Stub()
    assert isinstance(stub, DataStore)

    config = SDKConfig(data=_DIRECT_CONFIG, data_store=stub)
    core = Core(config).initialize()
    try:
        ctx = core.create_context("visitor-7")
        ctx.track_conversion("purchase_completed")
        assert any(k.startswith("dedup:") for k in stub._d.keys())
    finally:
        core.close()


def _injected_keys(store: InMemoryDataStore):
    """Best-effort introspection of the store's backing dict keys for assertion."""
    for value in vars(store).values():
        if isinstance(value, dict):
            return list(value.keys())
    return []


# --- Story 3.2 — mutable visitor state round-trip through the store ---------

_AUDIENCE_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "audiences": [
        {
            "id": "a1",
            "key": "us-only",
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
    ],
    "experiences": [
        {
            "id": "e2",
            "key": "us-experience",
            "audiences": ["a1"],
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        }
    ],
    "features": [],
    "goals": [],
    "segments": [],
}


def test_set_attributes_round_trip_through_shared_store(in_memory_store):
    # End-to-end through the public SDK surface, offline, using the qs-06 shared
    # in_memory_store fixture: create -> set_attributes -> re-create -> evaluate
    # reflects the updated, persisted state (AC #2/#3).
    config = SDKConfig(data=_AUDIENCE_CONFIG, data_store=in_memory_store)
    core = Core(config).initialize()
    try:
        ctx = core.create_context("visitor-rt", visitor_attributes={"country": "CA"})
        # Initially does not qualify for the US-only experience.
        assert ctx.run_experience("us-experience") is None

        # Persist a visitor-attribute update through the store.
        ctx.set_attributes({"country": "US"})
        assert ctx.run_experience("us-experience") is not None

        # A FRESH context for the same visitor rehydrates the persisted update
        # from the SAME injected store and now qualifies.
        ctx2 = core.create_context("visitor-rt")
        assert dict(ctx2.visitor_attributes) == {"country": "US"}
        assert ctx2.run_experience("us-experience") is not None

        # The persisted state is observable through the injected store under a
        # visitor-scoped state key (not a dedup key).
        keys = _injected_keys(in_memory_store)
        assert any(k.startswith("state:") and "visitor-rt" in k for k in keys)
    finally:
        core.close()


def test_round_trip_is_visitor_scoped(in_memory_store):
    config = SDKConfig(data=_AUDIENCE_CONFIG, data_store=in_memory_store)
    core = Core(config).initialize()
    try:
        core.create_context("v_a", visitor_attributes={"country": "CA"}).set_attributes(
            {"country": "US"}
        )
        # A different visitor never persisted anything → hydrates empty and does
        # not see v_a's update (no clobber across visitors).
        ctx_b = core.create_context("v_b")
        assert dict(ctx_b.visitor_attributes) == {}
        assert ctx_b.run_experience("us-experience") is None
    finally:
        core.close()
