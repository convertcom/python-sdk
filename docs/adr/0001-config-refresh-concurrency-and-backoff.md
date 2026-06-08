# ADR 0001 — Config-refresh snapshot-swap concurrency and backoff parameters

- **Status:** Accepted (ratified 2026-06-08)
- **Story:** 5.2 — Add Post-MVP Automatic Config Refresh (FR31, architecture Phase 2)
- **Audit findings addressed:** F-027 (concurrency mechanism), F-028 (backoff parameters)

## Context

Story 5.2 introduces an opt-in background daemon thread (`ConfigRefresher`) that
periodically re-fetches remote config and replaces the live `ConfigSnapshot` on
`Core`. The architecture states only that *"Snapshot swap must be atomic from
the perspective of an evaluating caller"* and **does not** prescribe the
concurrency mechanism. Separately, the architecture (architecture.md lines
694–696) **defers all retry/backoff parameters to a Phase-2 ADR** and forbids
any retry implementation from landing without one. This ADR ratifies both
decisions so the story can reach completion.

Two hard constraints frame the decision:

1. The refresh worker runs on a **separate daemon thread** while evaluation and
   `create_context` calls run on the host's request threads. Reads and the swap
   write race by construction.
2. The SDK targets CPython 3.9+ **including free-threaded CPython 3.13+**. We may
   **not** rely on the undocumented GIL guarantee that a single attribute
   assignment is atomic — that guarantee evaporates under a free-threaded build
   and under alternative runtimes.

## Decision 1 — Concurrency: mutex-protected snapshot swap (F-027)

The live snapshot is read and written under a single `threading.Lock` held on
`Core` (`Core._snapshot_lock`):

- **Write (refresh path):** `Core._apply_refreshed_snapshot(snapshot)` acquires
  the lock, rebinds `self._snapshot` and re-points tracking metadata, then
  releases. The lock is held only for the constant-time rebind — no I/O, no
  validation, no serialization occurs inside the critical section (those happen
  on the worker thread *before* the lock is taken).
- **Read (evaluation path):** `Core.create_context` acquires the same lock,
  reads the current `self._snapshot` reference into a local, and releases before
  constructing the `Context`. The `Context` is built from — and retains — that
  single captured reference for its whole lifetime.

### Why this is atomic from an evaluating caller's perspective

`ConfigSnapshot` is a frozen, deep-immutable value object (collections wrapped in
`MappingProxyType`, indexes precomputed at construction). A caller therefore
observes **either** the entire previous snapshot **or** the entire new one, never
a partially-mutated hybrid — we never mutate a snapshot in place (Critical
Warning #2); we only rebind a reference. A long-lived `Context` keeps the
reference it captured at creation, giving a request a coherent view for its full
duration even if a swap fires mid-request.

### Why a mutex (and not lock-free / GIL-atomicity)

- **Free-threaded safety:** an explicit lock establishes a documented
  happens-before relationship between the worker's write and a reader's read on
  every CPython build, including free-threaded 3.13+, and on alternative
  runtimes. It does not depend on bytecode-level atomicity of `STORE_ATTR`.
- **Negligible cost:** the lock is uncontended in the common case (refresh is
  rare — minutes apart — relative to evaluation) and is held for a constant-time
  reference rebind, so it adds no measurable latency to the NFR5 evaluation
  budget.
- **Lock-free / RCU rejected:** an RCU or atomic-pointer scheme buys nothing here
  (Python has no user-facing atomic reference primitive in the stdlib) and would
  rest on the very GIL assumption we are required to avoid.

## Decision 2 — Backoff and interval parameters (F-028)

All values below are the ratified Phase-2 parameters; they are the defaults on
`RefreshConfig` and are caller-overridable. Validation
(`RefreshConfig.__post_init__`) enforces the invariants noted.

| Parameter | Default | Rationale | Invariant |
|-----------|---------|-----------|-----------|
| `interval_seconds` | `300.0` (5 min) | Matches the JS SDK's default `dataRefreshInterval` (300 000 ms). Long enough that polling cost is negligible for a long-running service; short enough that config drift heals within minutes. | `> 0` |
| `jitter_seconds` | `30.0` | Uniform random `[0, jitter]` added to each scheduled wait so a fleet of co-deployed processes does not synchronize their fetches (thundering-herd avoidance). 10 % of the interval is the conventional spread. | `0 <= jitter <= interval_seconds` |
| `backoff_factor` | `2.0` | Standard exponential-backoff base. Each consecutive transient failure doubles the wait, so a flapping endpoint is probed geometrically less often. | `>= 1.0` |
| `backoff_max_seconds` | `600.0` (10 min) | Ceiling on the backed-off wait. Guarantees AC-3's "never tight-loop a failing endpoint" while keeping recovery latency bounded at twice the base interval. | `>= interval_seconds` |

### Backoff algorithm

On a successful refresh the wait resets to `interval_seconds + U(0, jitter)`. On
a consecutive transient failure the wait grows as
`min(interval_seconds * backoff_factor ** consecutive_failures,
backoff_max_seconds)` plus jitter. The worker **never stops retrying** — once the
backed-off wait reaches `backoff_max_seconds` ("terminal backoff") the
`on_terminal_failure` callback is invoked (once per failure) so the host can
surface the typed error, but the previous good snapshot keeps serving and the
host process never crashes (AC-3).

## Consequences

- The lock is the single synchronization point for snapshot access; any future
  reader of the live snapshot must go through it.
- Backoff values are now a stable, documented contract. Changing a default is an
  ADR-superseding change, not an incidental code edit.
- Opt-out (`refresh=None`) remains byte-for-byte MVP: no lock contention occurs
  because no worker exists and `create_context` still takes the (uncontended)
  lock for a single rebind-free read — measured cost is a sub-microsecond
  uncontended acquire.
