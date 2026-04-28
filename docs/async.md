# Async and Framework Integrations (Design Intent)

> **Status:** Phase 3 — design recorded, not yet implemented.
> The MVP is sync-first and is fully supported. This document records
> the planned shape of async and framework support so the MVP code
> stays forward-compatible and integrators know what to expect.

## Why async is not in the MVP

The MVP ships a sync API because it covers the dominant Python backend
shape (Django/Flask request handlers, scripts, batch jobs) without any
asyncio entanglement. Adding async to the MVP would have:

- doubled the public API surface to maintain
- introduced event-loop concerns into a tool that does not need them
- delayed the parity-validation work that is more load-bearing than
  async support for shared cross-SDK correctness

The architecture deliberately deferred async to Phase 3 with one
constraint: **the MVP must not be async-hostile**. The audit recorded
in this PR confirms that constraint is satisfied.

## Sync–async coexistence model

When async lands, it lands as a parallel surface, not a replacement.

```text
                      ┌──────────────────────────────┐
                      │  evaluation/  (pure compute) │
                      │   bucketing, rules, features │
                      └──────────────┬───────────────┘
                                     │ shared
                ┌────────────────────┴────────────────────┐
                │                                         │
       ┌────────▼─────────┐                       ┌───────▼──────────┐
       │   Core (sync)    │                       │ AsyncCore (async)│
       │   create_context │                       │ async create_... │
       │   refresh_now    │                       │ async refresh_now│
       │   close          │                       │ aclose           │
       └────────┬─────────┘                       └───────┬──────────┘
                │                                         │
       ┌────────▼─────────┐                       ┌───────▼──────────┐
       │ Context (sync)   │                       │ AsyncContext     │
       │ run_experience   │                       │ async run_exp... │
       │ track_conversion │                       │ async track_...  │
       └────────┬─────────┘                       └───────┬──────────┘
                │                                         │
       ┌────────▼─────────┐                       ┌───────▼──────────┐
       │ Transport        │                       │ AsyncTransport   │
       │ httpx.Client     │                       │ httpx.AsyncClient│
       └──────────────────┘                       └──────────────────┘
```

**Five frozen rules for the async surface:**

1. **Async becomes a parallel API, not a replacement.** Sync stays
   first-class. There is no migration mandate.
2. **Shared evaluation core.** `bucketing`, `rules`, `segments`,
   `experiences`, `features`, `entity_lookup`, and `config_snapshot`
   are pure synchronous functions with no I/O. Both surfaces call
   them directly.
3. **Async transport adapter.** `Transport` keeps its sync Protocol;
   `AsyncTransport` is a new sibling Protocol whose methods are
   `async def`. `HttpxAsyncTransport` is the bundled adapter.
4. **DataStore stays sync for MVP.** `AsyncDataStore` is a new sibling
   Protocol. Sync `DataStore` adapters can be wrapped for async use
   via `asyncio.to_thread()` if a host has not yet adopted an async
   storage adapter.
5. **The SDK never owns the event loop.** Async callers provide their
   own loop; the SDK never calls `asyncio.run()` and never spawns a
   loop internally. Sync callers never encounter asyncio.

## Forward-compatibility audit (MVP code, today)

| Module                                    | Async status | Notes |
| ----------------------------------------- | ------------ | ----- |
| `evaluation/*`                            | ✅ ready      | Pure sync compute; reused as-is. |
| `domain/config_snapshot.py`               | ✅ ready      | Immutable dataclass + indexes; no I/O. |
| `domain/results.py`, `domain/context_state.py` | ✅ ready  | Immutable dataclasses; reused. |
| `ports/transport.py`                      | ➕ extend     | Add `AsyncTransport` Protocol alongside `Transport`. |
| `ports/storage.py`                        | ➕ extend     | Add `AsyncDataStore` Protocol alongside `DataStore`. |
| `ports/event_bus.py`                      | ✅ keep sync  | Handlers schedule their own async work; bus stays sync. |
| `adapters/transport/httpx_transport.py`   | ➕ sibling    | Add `HttpxAsyncTransport` using `httpx.AsyncClient`. |
| `adapters/storage/in_memory.py`           | ✅ ready      | Thread-safe; usable from async via `asyncio.to_thread()`. |
| `adapters/events/in_memory_event_bus.py`  | ✅ ready      | Sync handlers; async handlers can be scheduled via `asyncio.create_task()` in user-supplied wrappers. |
| `tracking/queue.py`                       | ✅ ready      | `threading.Lock`-protected; in-memory queue can be reused under async via `asyncio.to_thread()` or by wrapping with an `asyncio.Lock`-protected adapter. |
| `tracking/payloads.py`, `tracking/conversions.py` | ✅ ready | Pure compute; reused. |
| `config_loader/loader.py`                 | ➕ sibling    | Add `async def load_config_snapshot_async` mirroring the sync function. |
| `config_loader/refresh.py`                | ➕ sibling    | Sync daemon-thread refresher stays; `AsyncConfigRefresher` would be an asyncio-task variant for `AsyncCore`. |
| `core.py`                                 | ➕ sibling    | Add `AsyncCore` class with async lifecycle and `async create_context()`. |
| `context.py`                              | ➕ sibling    | Add `AsyncContext` class with async tracking calls. |
| `diagnostics.py`, `errors.py`, `events.py` | ✅ ready     | No I/O; reused. |

**No MVP module needs to change to enable async.** The seams above are
"add a sibling", never "rewrite". This is the architectural payoff for
the deferral discipline.

## Public method names already reserve async flexibility

The MVP names — `run_experience`, `run_feature`, `run_experiences`,
`run_features`, `track_conversion`, `flush_tracking`, `refresh_now`,
`close` — work as-is for both surfaces. The async surface gets the same
names on its `AsyncContext` / `AsyncCore` classes:

```python
# Sync (today)
result = context.run_experience("checkout-flow")
context.track_conversion("purchase")
core.refresh_now()
core.close()

# Async (planned, not shipped)
result = await async_context.run_experience("checkout-flow")
await async_context.track_conversion("purchase")
await async_core.refresh_now()
await async_core.aclose()
```

`AsyncCore.aclose()` follows the asyncio convention (cf.
`asyncio.StreamWriter.aclose`); the async context manager hooks
(`__aenter__` / `__aexit__`) round it out.

## Framework integrations

Framework helpers ship as separate distributions, not as part of the
core package. The core stays framework-free (NFR13) and usable in any
standard Python runtime (NFR14).

Planned distributions:

| Package                | Frameworks       | Provides                                   |
| ---------------------- | ---------------- | ------------------------------------------ |
| `convert-sdk-django`   | Django           | Middleware, request-scoped `Context`, settings integration. |
| `convert-sdk-fastapi`  | FastAPI/Starlette | Dependency-injection helpers, request-scoped `Context`. |
| `convert-sdk-flask`    | Flask            | Extension class, `g`-scoped `Context`. |

Each helper layers on top of the framework-agnostic `Core` /
`AsyncCore` surfaces. None of them entrench framework imports inside
the `convert_sdk` core package; uninstalling a helper does not remove
core functionality.

### Deprecation policy

When upstream frameworks make incompatible changes, the helper
distributions track them with normal semver discipline:

- Major-version bump in the upstream framework → major-version bump in
  the helper, with a deprecation period of at least one minor release
  on the prior major.
- Minor / patch upstream changes that affect the helper → minor /
  patch bump on the helper.
- Each helper release lists the supported upstream version range in
  its README and CI matrix.

## Cross-SDK parity coverage applies unchanged

Story 3.5's parity vectors (bucketing, rule, feature, state) describe
correctness contracts of the evaluation core. Because both sync and
async surfaces share that core, the same vectors test both. When
async ships, the parity job in `tests/parity/` runs the same fixtures
through `AsyncCore` / `AsyncContext` and asserts identical normalised
outcomes.

The cross-SDK diagnostic contract (Story 4.3 — `reason`,
`environment`, `bucket_value`, `variation_key`, hashed `visitor_ref`)
applies unchanged to async output.

## Open questions to resolve at Phase 3 sign-off

These are intentionally not decided yet. They will be settled when the
async API is opened for implementation:

- **Async transport boundary**: `httpx.AsyncClient` adapter vs.
  remaining sync at the transport boundary and offloading via
  `asyncio.to_thread()`. The architecture leans toward a real async
  adapter, but the wrapper approach is cheaper if Phase 3 is
  time-constrained.
- **DataStore Protocol shape**: a separate `AsyncDataStore` Protocol
  vs. a dual-protocol convention (one Protocol, two suites of
  methods — e.g., `load_context_state` / `aload_context_state`).
- **Async event bus**: keep the bus sync and let users schedule async
  work in handlers, or add a parallel `AsyncEventBus`. The architecture
  already lists "keep sync" as the leaning, but the framework-helper
  use cases may motivate a real async bus.

## Read next

- [Roadmap](roadmap.md) — phase boundaries and shipping status
- [Initialization § automatic config refresh](initialization.md#automatic-config-refresh-opt-in) — the Phase 2 surface that is shipped today
- [Extending](extending.md) — the Protocol-based extension model that
  carries forward into the async surface
