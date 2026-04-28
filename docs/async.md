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
| `adapters/storage/in_memory.py`           | ➕ wrap        | Thread-safe but synchronous; from async code, call through `asyncio.to_thread()` or supply an `AsyncDataStore` adapter. Not "drop-in async-ready." |
| `adapters/events/in_memory_event_bus.py`  | ➕ wrap        | Sync `emit()` invokes handlers on the calling thread, which would block the event loop if invoked from a coroutine. Async-aware use requires a small wrapper that schedules handlers via `asyncio.create_task`. |
| `tracking/queue.py`                       | ➕ wrap        | `threading.Lock`-protected; correct for sync use. From async code, calling `release()` directly would block the event loop — call it through `asyncio.to_thread()` or behind an `AsyncTrackingQueue` adapter. |
| `tracking/payloads.py`, `tracking/conversions.py` | ✅ ready | Pure compute; reused. |
| `config_loader/loader.py`                 | ➕ sibling    | Add `async def load_config_snapshot_async` mirroring the sync function. |
| `config_loader/refresh.py`                | ➕ sibling    | Sync daemon-thread refresher stays; `AsyncConfigRefresher` would be an asyncio-task variant for `AsyncCore`. |
| `core.py`                                 | ➕ sibling    | Add `AsyncCore` class with async lifecycle and `async create_context()`. |
| `context.py`                              | ➕ sibling    | Add `AsyncContext` class with async tracking calls. |
| `diagnostics.py`, `errors.py`, `events.py` | ✅ ready     | No I/O; reused. |

**No MVP module needs a destructive rewrite to enable async.** The seams
above are "add a sibling" or "wrap with an async adapter", never
"rewrite the existing class." `✅ ready` means "reusable verbatim from a
coroutine"; `➕ sibling` means "add a parallel async class"; `➕ wrap`
means "the sync class stays as-is but async callers must reach it
through an async adapter or `asyncio.to_thread()` to avoid blocking the
event loop."

## Public method names already reserve async flexibility

Most MVP names — `run_experience`, `run_feature`, `run_experiences`,
`run_features`, `track_conversion`, `flush_tracking`, `refresh_now` —
work as-is for both surfaces. The async surface gets the same names on
its `AsyncContext` / `AsyncCore` classes:

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

`AsyncCore.aclose()` is a deliberate exception: the asyncio convention
is to spell shutdown methods with the `a*` prefix (cf.
`asyncio.StreamWriter.aclose`), and an `await core.close()` reusing the
sync name would mislead readers about what is awaitable. The async
context-manager hooks (`__aenter__` / `__aexit__`) round it out.

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

The intent recorded above is the leaning architecture; the items below
are the specific points that Phase 3 sign-off needs to decide. Until
sign-off, the design above can shift on these axes:

- **Async transport implementation tactic**: the leaning is a real
  `HttpxAsyncTransport` built on `httpx.AsyncClient`, but `to_thread()`-
  wrapping the sync transport is a documented fallback if Phase 3 is
  time-constrained. The Protocol shape (`AsyncTransport` with `async
  def fetch_config` / `send_tracking`) is fixed either way; the
  question is which adapter ships first.
- **DataStore Protocol shape**: a separate `AsyncDataStore` Protocol
  (the leaning) vs. a dual-protocol convention (one Protocol, two
  suites of methods — e.g., `load_context_state` /
  `aload_context_state`). Picking the dual-protocol convention removes
  one type but couples the two surfaces tightly.
- **Async event bus**: keep the bus sync (the leaning) and let users
  schedule async work in handlers, or add a parallel `AsyncEventBus`.
  The framework-helper use cases may motivate a real async bus; the
  decision waits on those concrete requirements.
- **Concurrency limit for sync→async fallback**: if the `to_thread()`
  fallback is taken, the SDK should document the minimum
  `asyncio.get_event_loop().set_default_executor()` configuration
  needed to avoid head-of-line blocking under FastAPI burst load.

## Read next

- [Roadmap](roadmap.md) — phase boundaries and shipping status
- [Initialization § automatic config refresh](initialization.md#automatic-config-refresh-opt-in) — the Phase 2 surface that is shipped today
- [Extending](extending.md) — the Protocol-based extension model that
  carries forward into the async surface
