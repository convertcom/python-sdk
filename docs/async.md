# Async and Framework Integration — Design Intent (Phase 3)

> **Status: 🔭 planned — not implemented.** This document records the *design
> intent* for the Phase 3 async public API and framework-integration helpers so
> that the shipped MVP code does not foreclose them. **No async code, async
> transport adapter, or framework distribution exists in this package today.**
> Opening any of these surfaces for implementation requires **explicit Phase 3
> sign-off** (see [roadmap.md](roadmap.md)).
>
> The code shapes shown below are *illustrative of the planned API* — they are
> deliberately **not** executable samples and are not exercised by the docs test
> suite, because the symbols they reference (`AsyncCore`, `AsyncContext`,
> `AsyncTransport`, framework helpers) do not yet exist.

Today's async-Python users can already call the sync SDK from async code by
offloading to a worker thread:

```python
# Available TODAY — no async SDK surface required.
import asyncio
from convert_sdk import Core, SDKConfig

core = Core(SDKConfig(data=my_config)).initialize()

async def evaluate(visitor_id: str):
    ctx = core.create_context(visitor_id)
    # Offload the (CPU-bound, non-blocking) evaluation to a thread so it never
    # blocks the event loop. Network-touching config refresh already runs on its
    # own daemon thread.
    return await asyncio.to_thread(ctx.run_experience, "homepage-hero")
```

The Phase 3 work below adds a *native* async surface so callers do not have to
reach for `asyncio.to_thread()` themselves — but it never replaces the sync API.

---

## Sync–async coexistence model

The architecture freezes the interaction model so async can be introduced
without a rewrite or fork. The five rules below are binding when the async
surface lands:

1. **Async is a parallel API, not a replacement.** The sync API
   (`Core` / `Context`) remains the primary, first-class supported surface. An
   async surface (`AsyncCore` / `AsyncContext` or equivalent) is added
   *alongside* it — never as a migration target that deprecates sync.

2. **Shared synchronous evaluation core.** Bucketing, rule evaluation, feature
   resolution, segment matching, and config-snapshot reads are pure synchronous
   computation with **no I/O**. The async surface calls this code directly — it
   does **not** need async versions of evaluation functions. (Verified: see the
   forward-compatibility audit below.)

3. **Async transport adapter.** The `Transport` Protocol gains an async sibling
   (`AsyncTransport`) implemented on `httpx.AsyncClient`. Config fetch and
   tracking delivery are the *only* operations that become async. The shipped
   `HttpxTransport` is already built on `httpx`, which provides both `Client`
   and `AsyncClient`, so this is an additive adapter — not a rewrite of the
   transport boundary.

4. **The tracking queue stays thread-safe.** The MVP queue uses
   `threading.Lock`. Async callers can use the same queue mediated through
   `asyncio.to_thread()`, or a thin async wrapper / `asyncio.Lock`-backed
   sibling can be added. Because the MVP queue is **already** thread-safe, it
   does not need to be replaced when async lands.

5. **The SDK never owns the event loop.** It must never call `asyncio.run()`
   internally or create its own loop. Async callers provide the loop context;
   sync callers never encounter asyncio. Config refresh remains a daemon thread
   (not an asyncio task) so it works identically for sync and async callers.

A sixth rule governs storage:

6. **`DataStore` stays sync; an `AsyncDataStore` sibling is added.** The frozen
   four-method `DataStore` Protocol remains the sync contract. An
   `AsyncDataStore` variant is added in parallel for async-native adapters; the
   sync store can also be wrapped via `asyncio.to_thread()`. Whether to ship a
   second Protocol or a dual-mode design is an open Phase-3 question (below).

---

## Forward-compatibility audit

This is the Task 4 deliverable: an audit of **every module in the current MVP
source tree** (post–Story 5.2) for sync-only assumptions that would block a
future async wrapper. Verdicts were checked against the code on disk, not
assumed.

**Verdict vocabulary:**

- **async-ready** — pure compute or already thread-safe; the async surface reuses
  the module *as-is* with no change.
- **extend-with-sibling** — the module is correct for sync and must **not** be
  rewritten; async support arrives as a new sibling (an async Protocol variant,
  an `httpx.AsyncClient` adapter, an `AsyncCore`/`AsyncContext` facade) that
  reuses this module's logic.

| Module | Verdict | Rationale |
|--------|---------|-----------|
| `evaluation/bucketing.py`, `rules.py`, `segments.py`, `experiences.py`, `features.py`, `entity_lookup.py` | **async-ready** | Pure synchronous computation, no I/O, no shared mutable state. The async surface calls these directly (coexistence rule #2). |
| `domain/config_snapshot.py`, `context_state.py`, `results.py` | **async-ready** | Immutable dataclasses / value objects. Safe to read from any thread or coroutine. |
| `tracking/payloads.py`, `tracking/conversions.py`, `tracking/deduplication.py` | **async-ready** | Pure serialization / dedup-key derivation; stdlib-only, no I/O. |
| `tracking/queue.py` | **async-ready** | Already thread-safe via a per-instance `threading.Lock` (coexistence rule #4). Reused unchanged; an async wrapper is optional, not required. |
| `adapters/storage/in_memory.py` | **async-ready** | Per-instance `threading.Lock`, monotonic-clock TTL, no module/class global state. Safe under concurrent async-mediated access. |
| `adapters/events/in_process.py` | **async-ready** | Synchronous fan-out to handlers; isolates and swallows handler errors. An async event bus is an optional sibling, not a precondition. |
| `errors.py`, `events.py`, `logging.py`, `config.py`, `version.py` | **async-ready** | Type/constant/exception definitions and a stdlib `logging` seam — no runtime behavior to make async. |
| `_internal/redaction.py` | **async-ready** | Pure string/fingerprint helpers. |
| `config_loader/normalizer.py`, `validators.py` | **async-ready** | Pure transformation/validation over decoded payloads; no I/O. |
| `ports/transport.py` | **extend-with-sibling** | Sync `Transport` Protocol (`fetch_config` / `send_tracking` / `close`). Add an `AsyncTransport` sibling Protocol with `async def` equivalents (coexistence rule #3). The module's docstring already anticipates this. |
| `ports/storage.py` | **extend-with-sibling** | Sync `DataStore` Protocol (four frozen methods). Add an `AsyncDataStore` sibling (rule #6). The four-method freeze is what *makes* this a clean sibling rather than a re-shape. |
| `ports/event_bus.py` | **extend-with-sibling** | Sync `EventBus` Protocol. Its docstring explicitly anticipates "an async/queued implementation later without touching the emission call sites." Add an async sibling if async-native delivery is wanted. |
| `adapters/transport/httpx_transport.py` | **extend-with-sibling** | Sync adapter on `httpx.Client`. Add a sibling `HttpxAsyncTransport` on `httpx.AsyncClient` — same query/route builders, same error mapping; sync adapter is untouched. |
| `config_loader/loader.py` | **extend-with-sibling** | The `load_snapshot` pipeline calls the (sync) transport then runs pure validation/normalization. An async loader awaits an `AsyncTransport` then reuses the *same* pure post-processing. No rewrite — the pure stages are shared. |
| `config_loader/refresh.py` | **extend-with-sibling** | Story 5.2's `ConfigRefresher` is a sync daemon-thread worker (correct per coexistence rule #5 — SDK never owns the loop). An async surface needs its own scheduler tied to the host event loop; the daemon-thread refresher is reused unchanged by sync callers. |
| `core.py` | **extend-with-sibling** | `Core` composes transport + loader + queue + event bus and exposes the sync public API (`run_*`, `track_conversion`, `flush`, `refresh_now`, `close`, context-manager). `AsyncCore` is a parallel facade that reuses the same evaluation core and domain objects, swapping only the I/O-touching collaborators for async siblings. `Core` is **not** rewritten. |
| `context.py` | **extend-with-sibling** | `Context` exposes the per-visitor evaluation/tracking API over the shared sync evaluation functions. `AsyncContext` is a parallel facade reusing the same pure logic; `Context` is **not** rewritten. |

### Audit bottom line

**No shipped MVP module must be rewritten to enable async.** The pure evaluation
core, domain objects, payload/dedup helpers, and the thread-safe queue and
in-memory store are reused *as-is*; the four I/O-/loop-touching seams
(`ports/transport.py`, `ports/storage.py`, `ports/event_bus.py`,
`adapters/transport/httpx_transport.py`) and the three composition facades
(`config_loader/loader.py`/`refresh.py`, `core.py`, `context.py`) gain async
**siblings** that reuse the existing logic. The architecture's "MVP must not be
async-hostile" preparation was effective.

---

## Public method-name reservation

To preserve naming flexibility for an eventual async-by-default convention
(Critical Warning #5), the async surface follows these reservations rather than
renaming the sync API:

- The sync verbs — `run_experience`, `run_experiences`, `run_feature`,
  `run_features`, `run_custom_segments`, `track_conversion`, `flush`,
  `refresh_now`, `close` — are retained as-is on the sync `Core` / `Context`.
- The async surface uses the **`a`-prefix asyncio convention** for its methods
  (e.g. `arun_experience`, `atrack_conversion`, `aflush`, `aclose`) **or**
  exposes identically named coroutines on the distinct `AsyncCore` /
  `AsyncContext` types. The final choice is a Phase-3 sign-off decision (below);
  either way, no sync name is locked in a way that would clash.
- `close()` / `__exit__` (sync) and `aclose()` / `__aexit__` (async) coexist —
  the async context-manager protocol is additive.

---

## Framework integrations

Framework helpers are **separate distributions** layered on the framework-free
core — they are never imported into `convert_sdk` core (NFR13).

- **Distributions:** `convert-sdk-django`, `convert-sdk-fastapi`,
  `convert-sdk-flask` (placement — separate repos vs in-tree namespace packages —
  is a Phase-3 sign-off decision). The core `convert-python-sdk` distribution
  remains usable with **zero** framework dependency.
- **Minimum each helper provides:** request-scoped `Context` construction,
  dependency-injection / middleware wiring, and lifecycle wiring (initialize on
  startup, `flush()` / `close()` on shutdown — mapped onto each framework's
  lifecycle hooks).
- **Deprecation policy:** each helper pins a supported range of its upstream
  framework. When the framework makes a breaking change, the helper ships a new
  major version supporting the new range; the prior major receives a deprecation
  notice and a documented support window. The **core SDK never** takes on a
  framework version constraint as a result.

---

## Cross-SDK contract reuse

The async and framework surfaces reuse the existing cross-SDK contracts
**unchanged** — they do not re-derive or fork them:

- **Story 3.5 JavaScript-parity vectors (AC-3).** The same parity fixtures under
  `tests/parity/` must produce the **same normalized outcomes** when replayed
  through the async surface or through any parity-critical framework helper. This
  is a **hard requirement** when that code lands: the async path runs the same
  vectors and must match the sync path bit-for-bit on evaluation, tracking, and
  state behavior. (This is how AC-3 is satisfied at the design-intent level in
  this story — the parity discipline is reserved as a binding constraint, not
  re-implemented now.)
- **Story 4.3 cross-SDK diagnostic field contract.** Async diagnostic output
  uses the same comparable fields as the sync surface.
- **Story 4.4 extension Protocols.** Async paths accept the same adapters; the
  async Protocol siblings are signature-compatible analogues, not a new
  extension model.

---

## Open questions (Phase 3 sign-off decisions)

These are deliberately **left open** — they are architecture-level decisions that
require explicit Phase 3 sign-off and must not be pre-empted by MVP work:

1. **Async transport boundary.** Ship a native `AsyncTransport` on
   `httpx.AsyncClient`, or keep the transport sync-only and offload via
   `asyncio.to_thread()` at the `AsyncCore` boundary? (Trade-off: true async I/O
   vs. minimal surface area.)
2. **`DataStore` Protocol shape.** A separate `AsyncDataStore` Protocol, or a
   dual-mode Protocol convention that accepts both sync and async adapters?
3. **Async event bus.** Reuse the sync `EventBus` with handler scheduling onto
   the loop, or add a parallel `AsyncEventBus`?
4. **Async method naming.** `a`-prefixed methods on a shared type vs. distinct
   `AsyncCore` / `AsyncContext` types with identically named coroutines.

---

## Related documents

- [roadmap.md](roadmap.md) — the phase roadmap and shipped-vs-planned status.
- [extending.md](extending.md) — the shipped sync extension Protocols this design
  builds on.
- [ADR 0001](adr/0001-config-refresh-concurrency-and-backoff.md) — the shipped
  Phase 2 refresh worker referenced in the audit.
