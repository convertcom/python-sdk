"""qs-02 PY-4 -- process-wide, thread-safe, 60s-TTL memo for the ``?exp=``
config-by-experience fetch (AC8 memoization; supporting invariants: never
DataStore, cross-tenant isolation, thread-safety).

RED phase (TDD): ``HttpxTransport.fetch_config_by_experience`` does not exist
yet, so every test in this file fails at the first call to it (an
``AttributeError`` on the ``HttpxTransport`` class) -- not a collection-time
import error. The ``_clear_process_wide_memo`` autouse fixture additionally
pins two new module-level names on ``convert_sdk.adapters.transport.
httpx_transport`` that GREEN must add: ``_CONFIG_BY_EXPERIENCE_CACHE`` (the
process-wide memo dict) and a monkeypatchable wall-clock seam ``_now`` (see
decision log I-record for this task -- ``_now`` is the seam GREEN needs to add
for TTL expiry to be testable without real sleeping; a bare module-level
binding such as ``_now = time.time`` satisfies every test here).

Design grounded in:

* qs-02 contract Section 2 ("Resolution": "Memoize per experience_id,
  process-wide, TTL 60 s (in-memory only; never the DataStore)") and AC8.
* Decision log P3 (module-level, thread-safe, process-wide,
  ``sdk_key:experience_id``-keyed, 60s wall-clock TTL, never DataStore).
* The JS reference (structural precedent only -- this is NOT a
  bucketing/rule/feature-resolution algorithm, so JS is not the parity oracle
  here, per this agent's own operating charter -- but the shape is a useful,
  already-implemented sibling design to mirror):
  ``../javascript-sdk`` ``packages/api/src/api-manager.ts:38-50,344-381``
  (module-level ``configByExperienceCache`` Map, ``CONFIG_BY_EXPERIENCE_TTL =
  60000`` ms, cache key ``${sdkKey}:${experienceId}``, failed fetches evicted
  so a retry is possible) and
  ``packages/api/tests/api-manager-config-by-experience.tests.ts`` "AC8:
  process-wide memoization with 60s TTL" describe block, which this file's
  test cases map onto 1:1 (same-id-within-TTL, different-id, cross-instance
  same sdkKey, different-sdkKey-not-shared, TTL-expiry-refetch,
  failed-fetch-not-memoized). The `Date.now` monkeypatch JS uses to test TTL
  expiry deterministically is the direct precedent for this file's ``_now``
  monkeypatch seam.

Two cases have NO JS precedent (Python-specific, since the JS reference is
single-threaded and never needs cross-thread coordination) and are new,
spec-silent test-design decisions recorded in the decision log:

* Thread-safety / no-double-fetch race under genuine concurrent access.
* The "never DataStore" structural + spy invariant (JS has no DataStore
  concept at this layer at all).

All HTTP is mocked at the route level with RESPX -- no real network, no
socket-level patching (qs-06 pattern), matching ``tests/test_httpx_transport.py``.
"""

from __future__ import annotations

import inspect
import threading
import time
from typing import Any, Dict, List

import httpx
import pytest
import respx

import convert_sdk.adapters.transport.httpx_transport as httpx_transport_module
from convert_sdk.adapters.storage.in_memory import InMemoryDataStore
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.errors import ConfigLoadError


CONFIG_BODY: Dict[str, Any] = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [],
}

#: A fixed, arbitrary wall-clock instant used as the base for every
#: monkeypatched ``_now()`` in this file (epoch-seconds, matching
#: ``time.time()``'s unit -- decision P3: wall-clock, not monotonic).
FIXED_NOW = 1_700_000_000.0

#: Decision P3 / JS parity (``CONFIG_BY_EXPERIENCE_TTL = 60000`` ms).
TTL_SECONDS = 60.0

_ROUTE_REGEX = r"https://cdn-4\.convertexperiments\.com/api/v1/config/.*"


@pytest.fixture(autouse=True)
def _clear_process_wide_memo():
    """The exp= config memo is process-wide (module-level, decision P3) -- it
    MUST be cleared before and after every test in this file, otherwise a
    cache entry populated by one test would silently satisfy (or corrupt) the
    hit-count assertions of a later, unrelated test. Locates the memo dict
    under the guarding lock so a partially-run concurrent test never leaves
    the fixture itself racing the cache it is trying to clear.
    """
    with httpx_transport_module._CONFIG_BY_EXPERIENCE_LOCK:
        httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE.clear()
    yield
    with httpx_transport_module._CONFIG_BY_EXPERIENCE_LOCK:
        httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE.clear()


def _patch_clock(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    monkeypatch.setattr(httpx_transport_module, "_now", lambda: value)


class _SpyDataStore(InMemoryDataStore):
    """Records every ``get``/``set`` call so a test can assert zero-touch."""

    def __init__(self) -> None:
        super().__init__()
        self.get_calls: List[str] = []
        self.set_calls: List[Any] = []

    def get(self, key: str) -> Any:
        self.get_calls.append(key)
        return super().get(key)

    def set(self, key: str, value: Any, ttl: Any = None) -> None:
        self.set_calls.append((key, value, ttl))
        super().set(key, value, ttl)


# --- AC8: same id within the TTL window -> exactly one fetch -----------------


@respx.mock
def test_two_resolutions_within_ttl_trigger_exactly_one_fetch(monkeypatch):
    _patch_clock(monkeypatch, FIXED_NOW)
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    first = transport.fetch_config_by_experience(cfg, "exp-memo-same-id")
    second = transport.fetch_config_by_experience(cfg, "exp-memo-same-id")
    transport.close()

    assert len(route.calls) == 1
    assert first == CONFIG_BODY
    assert second == first


@respx.mock
def test_resolution_still_memoized_just_before_ttl_boundary(monkeypatch):
    """59s later (still inside the 60s window) must NOT trigger a refetch --
    boundary-safety companion to the expiry test below."""
    clock = {"t": FIXED_NOW}
    monkeypatch.setattr(httpx_transport_module, "_now", lambda: clock["t"])
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    transport.fetch_config_by_experience(cfg, "exp-memo-boundary")
    clock["t"] = FIXED_NOW + (TTL_SECONDS - 1)
    transport.fetch_config_by_experience(cfg, "exp-memo-boundary")
    transport.close()

    assert len(route.calls) == 1


# --- AC8: different experience_id -> its own fetch ----------------------------


@respx.mock
def test_different_experience_id_triggers_its_own_fetch(monkeypatch):
    _patch_clock(monkeypatch, FIXED_NOW)
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    transport.fetch_config_by_experience(cfg, "exp-memo-diff-a")
    transport.fetch_config_by_experience(cfg, "exp-memo-diff-b")
    transport.close()

    assert len(route.calls) == 2


# --- AC8: process-wide -- shared across independent transport instances ------


@respx.mock
def test_memo_shared_across_different_transport_instances_same_sdk_key(monkeypatch):
    """'Process-wide, not per-Core' (decision P3) -- two independently
    constructed ``HttpxTransport`` instances (as two ``Core`` instances would
    each own) sharing the same ``sdk_key`` must collapse into one fetch."""
    _patch_clock(monkeypatch, FIXED_NOW)
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    cfg = SDKConfig(sdk_key="sdkkey123")
    transport_a = HttpxTransport(TransportConfig())
    transport_b = HttpxTransport(TransportConfig())

    first = transport_a.fetch_config_by_experience(cfg, "exp-memo-cross-instance")
    second = transport_b.fetch_config_by_experience(cfg, "exp-memo-cross-instance")
    transport_a.close()
    transport_b.close()

    assert len(route.calls) == 1
    assert second == first


# --- memo key isolation: different sdk_key OR experience_id never collide ----


@respx.mock
@pytest.mark.parametrize(
    ("first_sdk_key", "first_experience_id", "second_sdk_key", "second_experience_id"),
    [
        pytest.param(
            "sdkkey123",
            "exp-memo-cross-sdkkey",
            "sdkkey456",
            "exp-memo-cross-sdkkey",
            id="different_sdk_key_same_experience_id",
        ),
        pytest.param(
            "sdkkey123",
            "exp-memo-a",
            "sdkkey123",
            "exp-memo-b",
            id="same_sdk_key_different_experience_id",
        ),
    ],
)
def test_different_sdk_key_or_experience_id_never_collide(
    monkeypatch,
    first_sdk_key,
    first_experience_id,
    second_sdk_key,
    second_experience_id,
):
    """AC8 / decision P3 cross-tenant safety: the memo key is
    ``f"{sdk_key}:{experience_id}"`` -- varying either half must never reuse
    the other's cached fetch."""
    _patch_clock(monkeypatch, FIXED_NOW)
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    transport.fetch_config_by_experience(SDKConfig(sdk_key=first_sdk_key), first_experience_id)
    transport.fetch_config_by_experience(SDKConfig(sdk_key=second_sdk_key), second_experience_id)
    transport.close()

    assert len(route.calls) == 2


# --- AC8: TTL expiry -> refetch -----------------------------------------------


@respx.mock
def test_second_resolution_after_ttl_expiry_triggers_second_fetch(monkeypatch):
    clock = {"t": FIXED_NOW}
    monkeypatch.setattr(httpx_transport_module, "_now", lambda: clock["t"])
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    transport.fetch_config_by_experience(cfg, "exp-memo-ttl")
    clock["t"] = FIXED_NOW + TTL_SECONDS + 1  # 61s later -- past the window
    transport.fetch_config_by_experience(cfg, "exp-memo-ttl")
    transport.close()

    assert len(route.calls) == 2


# --- unbounded growth: expired entries are swept on write (review R1) -------


@respx.mock
def test_write_sweeps_expired_entries_but_keeps_ttl_boundary_intact(monkeypatch):
    """Code-review finding R1 (Ruby sibling parity, ruby-sdk#41): overwriting a
    same-key entry must never be the ONLY eviction path, or the memo grows
    unbounded with every distinct ``experience_id`` a preview link ever named
    over the process lifetime. Populate three distinct keys, advance the clock
    past the TTL, then trigger a write for exactly one of them -- ALL expired
    entries (not just the re-fetched key) must be swept from the dict, while
    AC8 (one fetch per key within the TTL) still holds for a fresh key created
    by the same sweeping write.
    """
    clock = {"t": FIXED_NOW}
    monkeypatch.setattr(httpx_transport_module, "_now", lambda: clock["t"])
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    transport.fetch_config_by_experience(cfg, "exp-sweep-a")
    transport.fetch_config_by_experience(cfg, "exp-sweep-b")
    transport.fetch_config_by_experience(cfg, "exp-sweep-c")
    assert len(httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE) == 3

    clock["t"] = FIXED_NOW + TTL_SECONDS + 1  # 61s later -- all three expired
    transport.fetch_config_by_experience(cfg, "exp-sweep-a")  # triggers the sweep
    transport.close()

    cache = httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE
    assert len(cache) == 1
    assert set(cache) == {"sdkkey123:exp-sweep-a"}
    assert len(route.calls) == 4  # 3 initial + 1 refetch of the expired "a"


@respx.mock
def test_write_sweep_does_not_disturb_still_fresh_entries_within_ttl(monkeypatch):
    """AC8 companion to the sweep test above: a write for a NEW key while an
    UNRELATED key is still within its TTL window must not evict the fresh
    entry, and resolving that fresh key again must still cost exactly one
    fetch (no accidental over-eviction)."""
    clock = {"t": FIXED_NOW}
    monkeypatch.setattr(httpx_transport_module, "_now", lambda: clock["t"])
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    transport.fetch_config_by_experience(cfg, "exp-sweep-fresh")
    clock["t"] = FIXED_NOW + (TTL_SECONDS - 1)  # still within the window
    transport.fetch_config_by_experience(cfg, "exp-sweep-new")
    transport.fetch_config_by_experience(cfg, "exp-sweep-fresh")  # still memoized
    transport.close()

    assert len(route.calls) == 2
    cache = httpx_transport_module._CONFIG_BY_EXPERIENCE_CACHE
    assert set(cache) == {"sdkkey123:exp-sweep-fresh", "sdkkey123:exp-sweep-new"}


# --- failed fetch is never memoized -> next call retries (JS parity) --------


@respx.mock
def test_failed_fetch_is_not_memoized_so_next_call_retries(monkeypatch):
    """Spec-silent, JS-parity design choice (decision log I-record): a failed
    fetch must not poison the cache for the remainder of the TTL window --
    otherwise a transient 503 during a QA preview session would strand the
    reviewer for 60s with no way to retry."""
    _patch_clock(monkeypatch, FIXED_NOW)
    route = respx.get(url__regex=_ROUTE_REGEX).mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=CONFIG_BODY),
        ]
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    with pytest.raises(ConfigLoadError):
        transport.fetch_config_by_experience(cfg, "exp-memo-reject-then-refetch")

    second = transport.fetch_config_by_experience(cfg, "exp-memo-reject-then-refetch")
    transport.close()

    assert len(route.calls) == 2
    assert second == CONFIG_BODY


# --- thread-safety: concurrent resolutions of the same key --------------------


@respx.mock
def test_concurrent_resolutions_of_same_key_trigger_exactly_one_fetch(monkeypatch):
    """Python-specific (no JS precedent -- JS is single-threaded): multiple
    threads resolving the SAME ``(sdk_key, experience_id)`` concurrently must
    collapse into exactly one transport fetch. Decision P3: the memo lock
    serializes the whole check+fetch+store sequence (not just the dict
    access), so every losing thread observes the already-populated cache
    instead of racing into its own duplicate fetch. A slow mocked response
    widens the race window so the assertion is deterministic rather than
    depending on RESPX's real latency happening to be fast enough to never
    expose a race even without a lock.
    """
    _patch_clock(monkeypatch, FIXED_NOW)

    def _slow_response(request: httpx.Request) -> httpx.Response:
        time.sleep(0.05)
        return httpx.Response(200, json=CONFIG_BODY)

    route = respx.get(url__regex=_ROUTE_REGEX).mock(side_effect=_slow_response)

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")

    thread_count = 6
    barrier = threading.Barrier(thread_count)
    results: List[Dict[str, Any]] = []
    errors: List[BaseException] = []
    results_lock = threading.Lock()

    def _worker() -> None:
        barrier.wait()
        try:
            body = transport.fetch_config_by_experience(cfg, "exp-memo-concurrent")
            with results_lock:
                results.append(body)
        except BaseException as exc:  # pragma: no cover - failure path only
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    transport.close()

    assert errors == []
    assert len(results) == thread_count
    assert all(body == CONFIG_BODY for body in results)
    assert len(route.calls) == 1


# --- never the DataStore -------------------------------------------------------


def test_signature_has_no_datastore_collaborator():
    """By construction: ``fetch_config_by_experience`` accepts only ``(config,
    experience_id)`` -- there is no ``DataStore`` parameter for it to write
    through, so "never the DataStore" holds structurally, mirroring the
    ``get_preview_decision`` precedent (``tests/test_preview_decision.py``
    ``test_signature_has_no_store_or_tracker_collaborator``)."""
    sig = inspect.signature(HttpxTransport.fetch_config_by_experience)
    params = [name for name in sig.parameters if name != "self"]
    assert params == ["config", "experience_id"]


@respx.mock
def test_never_writes_to_or_reads_from_datastore(monkeypatch):
    """Live spy companion to the structural test above: an ``InMemoryDataStore``
    that happens to exist in the same process (as ``Core`` would own one) is
    never touched by a memoized or fresh resolution."""
    _patch_clock(monkeypatch, FIXED_NOW)
    respx.get(url__regex=_ROUTE_REGEX).mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )
    store = _SpyDataStore()

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    transport.fetch_config_by_experience(cfg, "exp-memo-no-datastore")
    transport.fetch_config_by_experience(cfg, "exp-memo-no-datastore")  # memoized hit
    transport.close()

    assert store.get_calls == []
    assert store.set_calls == []
