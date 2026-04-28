# Roadmap

`convert-python-sdk` ships in phases that match the architecture's
deliberate-deferral discipline. The MVP is the sync-first surface;
later phases are additive — they layer on top without changing what
the MVP gives you today.

## Phase 1 — MVP (shipped)

The current package: a framework-agnostic, sync-first SDK for backend
Python services.

| Capability                          | Status   | Reference                         |
| ----------------------------------- | -------- | --------------------------------- |
| `Core` + `Context` evaluation API   | ✅ shipped | [`evaluation.md`](evaluation.md)  |
| Local experience and feature evals  | ✅ shipped | [`evaluation.md`](evaluation.md)  |
| `httpx` config fetch and tracking   | ✅ shipped | [`initialization.md`](initialization.md) |
| Conversion tracking + queue control | ✅ shipped | [`tracking.md`](tracking.md), [`queue-control.md`](queue-control.md) |
| Mutable visitor state and segments  | ✅ shipped | [`evaluation.md`](evaluation.md)  |
| Diagnostic logging + typed errors   | ✅ shipped | [`debugging.md`](debugging.md)    |
| Custom transport / storage adapters | ✅ shipped | [`extending.md`](extending.md)    |
| Cross-SDK parity fixtures           | ✅ shipped | `tests/parity/`                   |

## Phase 2 — Long-running service support

Additive features for services that stay running across many requests.

| Capability                            | Status   | Reference                                    |
| ------------------------------------- | -------- | -------------------------------------------- |
| Automatic config refresh (opt-in)     | ✅ shipped | [`initialization.md` § auto refresh](initialization.md#automatic-config-refresh-opt-in) |
| Bundled durable storage (SQLite/Redis) | 📋 planned | —                                            |
| Retry / backoff tuning surfaces       | 📋 planned | —                                            |
| Structured logging integration guide  | 📋 planned | —                                            |

Auto-refresh is opt-in: the default `SDKConfig.refresh=None` preserves
MVP behaviour byte-for-byte.

## Phase 3 — Enterprise extension points

Larger expansions that maintain the sync-first MVP as a first-class
supported surface.

| Capability                                         | Status   | Reference                          |
| -------------------------------------------------- | -------- | ---------------------------------- |
| Async public API (`AsyncCore` / `AsyncContext`)    | 📋 planned | [`async.md`](async.md)             |
| Async transport adapter (`httpx.AsyncClient`)      | 📋 planned | [`async.md`](async.md)             |
| Async data-store Protocol (`AsyncDataStore`)       | 📋 planned | [`async.md`](async.md)             |
| Django integration (`convert-sdk-django`)          | 📋 planned | separate distribution              |
| FastAPI integration (`convert-sdk-fastapi`)        | 📋 planned | separate distribution              |
| Flask integration (`convert-sdk-flask`)            | 📋 planned | separate distribution              |
| OpenTelemetry integration                           | 📋 planned | —                                  |

The framework helper packages ship as separate distributions; the core
`convert-python-sdk` distribution stays framework-free (NFR13). See
[`async.md`](async.md) for the async design intent.

## What does *not* change between phases

- **The sync API is permanent.** The async surface is *additive*; sync
  remains a first-class supported product. Migration is opt-in.
- **The evaluation core is shared.** Bucketing, rules, segments, feature
  resolution, and config-snapshot logic are pure synchronous compute.
  Both sync and async surfaces reuse the same evaluation modules
  byte-for-byte; parity vectors apply unchanged.
- **The cross-SDK diagnostic contract is shared.** Diagnostic field
  names, redaction rules, and `*Diagnostic` reason codes are identical
  across sync and async surfaces (see [`debugging.md`](debugging.md)).
- **Adapter Protocols generalise.** Sync `Transport`/`DataStore` keep
  working; async equivalents are added in parallel rather than as
  replacements.

## Tracking phase progress

Each phase ships behind a feature seam, never a hidden flag. Phase 2
features (e.g. auto-refresh) are opt-in via constructor configuration.
Phase 3 features either ship as separate distributions (framework
helpers) or as parallel classes alongside the sync API (async).
