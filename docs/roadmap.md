# Convert Python SDK — Expansion Roadmap

This document records the planned trajectory of the Convert Python SDK so that
consumers can see what ships today, what is in flight, and what is deliberately
deferred. It tracks the architecture's **phase boundaries** and the PRD's Module
Phase Table, and it follows the project's *deferral discipline*: a capability is
listed as **planned** until the code that implements it actually ships, at which
point its row flips to **shipped** with the story that delivered it.

> **Status legend** — ✅ shipped · 🚧 in progress · 🔭 planned (gated)

The roadmap is organized into three phases that mirror the architecture's
"Deferred Decisions (Post-MVP)" section:

| Phase | Theme | Status |
|-------|-------|--------|
| **Phase 1** | MVP — sync-first SDK | ✅ shipped |
| **Phase 2** | Long-running service support | 🚧 partially shipped |
| **Phase 3** | Enterprise extension points (async + frameworks + observability) | 🔭 planned (gated) |

---

## Phase 1 — MVP (shipped)

The MVP is a **sync-first**, framework-agnostic SDK that runs in any standard
Python 3.9+ runtime with no JavaScript runtime, browser, or sidecar dependency
(NFR13, NFR14). Everything below is shipped and covered by the test suite and
the JavaScript-parity fixtures (Story 3.5).

| Capability | Status | Notes |
|------------|--------|-------|
| `Core` + `SDKConfig` initialization (remote `sdk_key` / direct `data`) | ✅ | Context-manager lifecycle, env-sourced key. See [Initialization](initialization.md). |
| Experience & feature evaluation (`run_experience` / `run_experiences` / `run_feature` / `run_features`) | ✅ | Deterministic MurmurHash bucketing, parity-locked. See [Evaluation](evaluation.md). |
| Custom & default segments (`set_segments`, `run_custom_segments`) | ✅ | |
| Conversion tracking (`track_conversion`, batching, dedup, revenue) | ✅ | Thread-safe in-process queue. See [Tracking](tracking.md). |
| Queue control (`flush`, batch size, opt-in periodic timer, `atexit`) | ✅ | See [Queue control](queue-control.md). |
| Cross-SDK diagnostics (`diagnose_experience` / `_feature` / `_goal` / `_entity`) | ✅ | Closed `DiagnosticReason` vocabulary, redaction-safe logging. See [Debugging](debugging.md). |
| Extension Protocols (`Transport`, `DataStore`, `EventBus`) | ✅ | `@runtime_checkable`, injectable. See [Extending](extending.md). |
| Lifecycle events via `Core.on` | ✅ | |
| Maintainer release workflow (CI matrix, OIDC publish, towncrier) | ✅ | Story 5.1. See [Release process](release-process.md). |

---

## Phase 2 — Long-running service support (partially shipped)

Phase 2 hardens the SDK for long-lived server processes (gunicorn/uvicorn
workers, Celery, daemons) where a single `Core` instance lives across many
requests. The architecture lists four Phase 2 deferred decisions; the first has
now shipped.

| Capability | Status | Shipped by / planned for | Notes |
|------------|--------|--------------------------|-------|
| **Automatic config refresh** | ✅ shipped | **Story 5.2** | Opt-in `SDKConfig.refresh=RefreshConfig(...)` (FR31). A daemon thread periodically re-fetches config through the same `Transport` Protocol and atomically swaps the immutable snapshot, with exponential backoff and a `LifecycleEvent.CONFIG_UPDATED` event. **Off by default** — `refresh=None` preserves MVP behavior byte-for-byte. Ratified in [ADR 0001](adr/0001-config-refresh-concurrency-and-backoff.md). |
| Bundled durable storage adapters (SQLite / Redis) | 🔭 planned | Phase 2 | The `DataStore` Protocol is frozen to four methods (`get` / `set` / `has` / `delete`) precisely so a durable adapter is a *swap*, not a protocol change. No core change required when these land. |
| Retry / backoff tuning at the transport boundary | 🔭 planned | Phase 2 | MVP performs no automatic tracking-delivery retry (delivery failure is logged and surfaced via `API_QUEUE_RELEASED`). Config-refresh backoff already exists (ADR 0001); generalized transport retry policy is the remaining Phase 2 item. |
| Structured logging guidance | 🔭 planned | Phase 2 | The stdlib `logging.Logger` seam (`SDKConfig.logger`) is already the extension point; this is a documentation deliverable, not a code change. |

> **Deferral discipline check.** Auto-refresh shipped as an **opt-in** addition
> that does not alter the default sync MVP path — exactly the additive,
> non-forking shape the architecture prescribes for every Phase 2/3 capability.

---

## Phase 3 — Enterprise extension points (planned, gated)

Phase 3 is the **expansion** tier: an async public API, framework-specific
integration helpers, and richer observability. **None of this is implemented.**
The design intent is recorded in [docs/async.md](async.md) so the MVP code does
not foreclose these surfaces, but opening any of them for implementation
requires **explicit Phase 3 sign-off**.

| Capability | Status | Design intent | Gate |
|------------|--------|---------------|------|
| **Async public API** (`AsyncCore` / `AsyncContext` + `AsyncTransport`) | 🔭 planned | [async.md](async.md) — parallel API, shared sync evaluation core, async transport adapter on `httpx.AsyncClient`, SDK never owns the event loop. | Phase 3 sign-off |
| **Framework integrations** (`convert-sdk-django` / `-fastapi` / `-flask`) | 🔭 planned | [async.md](async.md#framework-integrations) — separate distributions layered on the framework-free core (NFR13); request-scoped context, DI/middleware, lifecycle wiring; documented deprecation policy. | Phase 3 sign-off |
| **OpenTelemetry & richer observability** | 🔭 planned | Traces/metrics around evaluation and tracking, built on the existing lifecycle-event and logging seams. | Phase 3 sign-off |

### Forward-compatibility guarantee

The MVP was designed so that Phase 3 lands as **siblings and extensions, never a
rewrite**. The detailed module-by-module forward-compatibility audit lives in
[async.md](async.md#forward-compatibility-audit). Its bottom line: no shipped
MVP module needs to change to enable async — the pure evaluation core is reused
directly, the tracking queue is already thread-safe, and the extension Protocols
(`Transport`, `DataStore`, `EventBus`) gain async siblings rather than being
re-shaped.

### Parity & contract reuse

When the async or framework surfaces land, they reuse the existing cross-SDK
contracts unchanged:

- **Story 3.5 JavaScript-parity vectors** apply to the async surface unchanged —
  the same fixtures must produce the same normalized outcomes (this is a hard
  requirement, not a re-derivation).
- **Story 4.3 diagnostic field contract** — async output uses the same
  comparable diagnostic fields.
- **Story 4.4 extension Protocols** — async paths accept the same adapters.

---

## Related documents

- [docs/async.md](async.md) — Phase 3 async + framework design intent and the
  forward-compatibility audit.
- [ADR 0001](adr/0001-config-refresh-concurrency-and-backoff.md) — the shipped
  Phase 2 auto-refresh concurrency and backoff decisions.
- [docs/index.md](index.md) — the documentation landing page.
