"""The SDK core orchestration surface (Story 1.2).

``Core`` is the public entry point for initialization, readiness, and current
config access. Story 1.1 froze the ``from convert_sdk import Core`` boundary as
an empty placeholder; Story 1.2 implements the first real behavior on top of it
without renaming the public surface.

Scope (Story 1.2): initialization (direct-config or ``sdkKey``), immutable
snapshot loading, and authoritative readiness state. ``Core`` does NOT implement
visitor-context creation, evaluation, bucketing, or tracking — those land in
later stories. The public API is sync-first for MVP.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from convert_sdk.config import SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.ports.storage import visitor_state_key

from convert_sdk._internal.redaction import SafeContext, redact_url
from convert_sdk.adapters.events.in_process import InProcessEventBus
from convert_sdk.adapters.storage.in_memory import InMemoryDataStore
from convert_sdk.events import LifecycleEvent
from convert_sdk.logging import log_safe

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.ports.event_bus import EventBus, EventHandler
    from convert_sdk.ports.storage import DataStore
    from convert_sdk.ports.transport import Transport


class Core:
    """Public entry point and orchestration surface for the Convert Python SDK.

    Args:
        config: The :class:`~convert_sdk.config.SDKConfig` describing how to
            initialize (direct ``data`` or remote ``sdk_key``).
        transport: Optional transport implementation. When omitted and an
            ``sdk_key`` is configured, an httpx-backed transport is created
            lazily at initialization time. Direct-config initialization never
            constructs or uses a transport.
    """

    def __init__(self, config: SDKConfig, *, transport: Optional["Transport"] = None) -> None:
        self._config = config
        self._transport: Optional["Transport"] = transport
        self._owns_transport = False
        self._snapshot: Optional[ConfigSnapshot] = None
        # Story 5.2 / ADR 0001: a single mutex guards every read and write of the
        # live snapshot reference so the background refresh swap is atomic from an
        # evaluating caller's perspective on EVERY CPython build (including
        # free-threaded 3.13+) — never relying on GIL attribute-assignment
        # atomicity. Held only for the constant-time rebind; no I/O inside it.
        self._snapshot_lock = threading.Lock()
        # Opt-in background refresh worker (None unless SDKConfig.refresh is set
        # AND the SDK is in remote mode). Created at initialize().
        self._refresher: Optional[Any] = None
        self._ready = False
        # Story 3.1: the composition root resolves and OWNS the single per-Core
        # DataStore. A configured store (SDKConfig.data_store) is honored as-is;
        # the default None maps to a fresh in-memory store so the SDK is fully
        # functional with zero external storage dependency. core.py is the ONLY
        # site allowed to import the concrete InMemoryDataStore (layering L4);
        # everything downstream receives it as a DataStore protocol type.
        self._data_store: "DataStore" = (
            config.data_store if config.data_store is not None else InMemoryDataStore()
        )
        # Story 2.3: the shared tracker (queue + dedup + flush) is created at
        # initialize() once the snapshot is available, and shared by every
        # context Core creates so dedup/batching are process-consistent.
        self._tracker: Optional[Any] = None
        # Opt-in daemonic periodic-flush driver (None unless configured).
        self._periodic_flusher: Optional[Any] = None
        # Story 2.4: ONE EventBus per Core, created eagerly so Core.on(...) is
        # usable before initialize() and the SAME bus is injected into the
        # tracker at initialize() (no per-context or per-call bus).
        self._event_bus: "EventBus" = InProcessEventBus()

    # --- lifecycle events --------------------------------------------------

    def on(self, event: LifecycleEvent, handler: "EventHandler") -> None:
        """Register a lifecycle-event ``handler`` for ``event`` (Story 2.4, FR40).

        The only public observability surface added by Story 2.4. Delegates to
        the single per-Core :class:`~convert_sdk.ports.event_bus.EventBus`; Core
        itself stays thin (no event-routing logic here). A handler that raises is
        isolated, logged, and swallowed by the bus — it can never break tracking
        or delivery (AC #2). Handlers are invoked as ``handler(payload, error)``.

        Safe to call before :meth:`initialize`.
        """
        self._event_bus.on(event, handler)

    # --- readiness & config access ----------------------------------------

    @property
    def is_ready(self) -> bool:
        """Authoritative readiness state. True only after a snapshot is loaded."""
        return self._ready

    @property
    def current_config(self) -> Optional[ConfigSnapshot]:
        """The current immutable config snapshot, or ``None`` if not ready.

        Read under the snapshot mutex (ADR 0001) so a concurrent background
        refresh swap is observed atomically — the caller sees the whole previous
        or the whole new snapshot, never a torn read.
        """
        with self._snapshot_lock:
            return self._snapshot

    # --- visitor context ---------------------------------------------------

    def create_context(
        self,
        visitor_id: str,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        *,
        location_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Context:
        """Create a visitor-scoped :class:`~convert_sdk.context.Context`.

        The context evaluates against the current immutable snapshot.
        ``visitor_attributes`` are copied into the context defensively; later
        caller mutations do not affect it. The created context is a
        caller-scoped per-visitor object — reuse means the caller keeps and
        reuses the returned :class:`Context`; ``Core`` does not cache contexts.
        Requires the SDK to be initialized.

        Args:
            visitor_id: The stable visitor identity used for deterministic
                bucketing.
            visitor_attributes: Optional stored visitor attributes (e.g.
                audience traits) used for audience qualification.
            location_attributes: Optional stored location attributes used for
                location-rule qualification.

        Raises:
            RuntimeError: if called before :meth:`initialize` (no snapshot).
        """
        # ADR 0001: capture the live snapshot reference under the mutex so a
        # concurrent refresh swap can never produce a torn read. The Context is
        # built from — and retains — this single captured reference for its whole
        # lifetime (coherent per-request view even if a swap fires mid-request).
        with self._snapshot_lock:
            snapshot = self._snapshot
        if snapshot is None:
            raise RuntimeError(
                "Core must be initialized before creating a context "
                "(call initialize() first)."
            )
        # Story 3.2: rehydrate any persisted per-visitor ContextState through the
        # SAME single per-Core DataStore + visitor-scoped key. Stored attributes
        # form the baseline; caller-supplied visitor_attributes for this fresh
        # context override matching keys (explicit construction wins). The read
        # is strictly visitor-scoped and goes through the DataStore protocol
        # only — Core (L4) owns the concrete store; downstream sees the protocol.
        hydrated, segments = self._hydrate_visitor_state(visitor_id, visitor_attributes)
        return Context(
            visitor_id,
            snapshot,
            visitor_attributes=hydrated,
            default_segments=segments,
            location_attributes=location_attributes,
            tracker=self._tracker,
            data_store=self._data_store,
            # Story 4.3: forward the config environment so per-visitor
            # diagnostics carry the cross-SDK-comparable environment qualifier.
            environment=self._config.environment,
        )

    def _hydrate_visitor_state(
        self,
        visitor_id: str,
        visitor_attributes: Optional[Mapping[str, Any]],
    ) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
        """Rehydrate persisted visitor attributes AND default segments.

        Reads this visitor's persisted ``ContextState`` envelope (written by
        :meth:`convert_sdk.context.Context.set_attributes` /
        :meth:`convert_sdk.context.Context.set_segments`) through the single
        per-Core ``DataStore`` and returns ``(attributes, default_segments)``.

        The persisted value is the structured envelope
        ``{"attributes": {...}, "segments": {...}}`` (Story 3.3). For backward
        compatibility a legacy Story 3.2 plain-attributes ``dict`` (no envelope)
        is treated as attributes-only with empty segments. Caller-supplied
        ``visitor_attributes`` for this fresh context overlay the persisted
        attributes (explicit construction wins). The read is strictly
        visitor-scoped and goes through the ``DataStore`` protocol only — Core
        (L4) owns the concrete store; downstream sees the protocol. Returns the
        caller value unchanged (and no segments) when nothing is persisted, so
        contexts for visitors that never persisted state behave exactly as
        before.
        """
        stored = self._data_store.get(visitor_state_key(visitor_id))
        stored_attributes: Mapping[str, Any] = {}
        stored_segments: Optional[Mapping[str, Any]] = None
        if isinstance(stored, Mapping) and stored:
            if "attributes" in stored or "segments" in stored:
                # Story 3.3 structured envelope.
                raw_attrs = stored.get("attributes")
                stored_attributes = raw_attrs if isinstance(raw_attrs, Mapping) else {}
                raw_segments = stored.get("segments")
                if isinstance(raw_segments, Mapping) and raw_segments:
                    stored_segments = dict(raw_segments)
            else:
                # Legacy Story 3.2 plain-attributes dict (attributes-only).
                stored_attributes = stored

        if not stored_attributes and not visitor_attributes:
            attributes: Optional[Mapping[str, Any]] = visitor_attributes
        else:
            merged = dict(stored_attributes)
            if visitor_attributes:
                merged.update(visitor_attributes)
            attributes = merged
        return attributes, stored_segments

    # --- tracking flush ----------------------------------------------------

    def flush(self) -> None:
        """Explicitly release the tracking queue and deliver queued events.

        Drains the shared queue through the single release path, serializes the
        batched per-visitor events via the Story 2.2 serializer, and delivers
        through the configured transport, clearing the queue on success. A flush
        on an empty queue is a safe no-op (no transport call, no error). This is
        the canonical, deterministic control point for queue release (FR39); the
        default lifecycle is explicit-flush-only.

        Safe to call before :meth:`initialize` (no tracker yet) — it is a no-op.
        """
        if self._tracker is not None:
            self._tracker.flush()

    # --- initialization ----------------------------------------------------

    def initialize(self) -> "Core":
        """Initialize the SDK from direct config data or by fetching via sdkKey.

        Direct-config initialization makes no network call. ``sdkKey``
        initialization fetches config over HTTPS through the transport.

        Raises:
            InvalidConfigError: if the (direct or fetched) config is malformed.
            ConfigLoadError: if the config fetch fails.
            TransportError: if a transport cannot be established (e.g. a
                non-HTTPS base URL — though that is enforced earlier, at
                ``TransportConfig`` construction).
        """
        # Additive diagnostic logging (Story 4.1): emit a config-load START
        # milestone, then a SUCCESS milestone carrying the config version, or a
        # FAILURE record on any load error. This wraps the existing init flow at
        # the orchestration seam WITHOUT changing its control flow or readiness
        # contract (Critical Warning #6) — a logging failure can never alter
        # initialization, and the original exception is always re-raised.
        endpoint = None if self._config.is_direct_config else self._config.transport.base_url
        log_safe(
            LifecycleEvent.CONFIG_UPDATED,
            level=logging.DEBUG,
            target=self._config.logger,
            context=SafeContext(endpoint=redact_url(endpoint)),
        )
        try:
            raw = self._load_raw_config()
            # load_snapshot validates + normalizes; any failure leaves us not-ready.
            self._snapshot = load_snapshot(raw)
        except Exception as error:
            status = getattr(error, "status_code", None)
            log_safe(
                LifecycleEvent.CONFIG_UPDATED,
                level=logging.ERROR,
                target=self._config.logger,
                context=SafeContext(endpoint=redact_url(endpoint), status_code=status),
            )
            raise
        self._build_tracker()
        self._ready = True
        log_safe(
            LifecycleEvent.READY,
            level=logging.INFO,
            target=self._config.logger,
            context=SafeContext(config_version=self._snapshot.project_id),
        )
        # Story 5.2: opt-in background refresh. Only started for a remote
        # (sdk_key) instance with a configured policy. refresh=None (default)
        # keeps MVP behavior byte-for-byte (Critical Warning #1).
        self._maybe_start_refresher()
        return self

    def _maybe_start_refresher(self) -> None:
        """Start the opt-in background config-refresh worker, if configured.

        No-op unless ``SDKConfig.refresh`` is set. Direct-config mode has no
        remote endpoint to poll, so a configured policy there spins up no worker
        and instead emits a ``refresh.skipped`` diagnostic rather than silently
        ignoring the misconfiguration (Critical Warning #7).
        """
        if self._config.refresh is None:
            return
        if self._config.is_direct_config:
            log_safe(
                LifecycleEvent.CONFIG_UPDATED,
                level=logging.WARNING,
                target=self._config.logger,
                refresh_phase="skipped",
                reason="direct_config_no_remote_endpoint",
            )
            return
        from convert_sdk.config_loader.refresh import ConfigRefresher

        self._refresher = ConfigRefresher(
            config=self._config,
            transport=self._ensure_transport(),
            on_snapshot=self._apply_refreshed_snapshot,
            on_terminal_failure=self._on_refresh_terminal_failure,
            logger=self._config.logger,
        )
        self._refresher.start()

    def _on_refresh_terminal_failure(self, error: BaseException) -> None:
        """Surface a terminal background-refresh failure (AC-3 typed-error channel).

        A persistently failing refresh keeps serving the prior good snapshot; this
        callback records the typed Story 4.2 error through the diagnostic logger
        so the failure is visible to operators WITHOUT crashing the host process.
        It is invoked on the worker thread and never re-raises.
        """
        status = getattr(error, "status_code", None)
        log_safe(
            LifecycleEvent.CONFIG_UPDATED,
            level=logging.ERROR,
            target=self._config.logger,
            context=SafeContext(status_code=status),
            refresh_phase="terminal_failure",
            error_code=getattr(error, "code", None),
        )

    def _build_tracker(self) -> None:
        """Create the shared tracking orchestrator from the loaded snapshot.

        Lazy-imported so the tracking layer (and httpx, via the transport
        provider) stays off the import path for callers that never track.
        """
        from convert_sdk.tracking.flush import setup_periodic_flush
        from convert_sdk.tracking.tracker import Tracker

        assert self._snapshot is not None
        self._tracker = Tracker(
            snapshot=self._snapshot,
            config=self._config,
            data_store=self._data_store,
            transport=self._transport,
            transport_provider=self._ensure_transport,
            event_bus=self._event_bus,
        )
        # Opt-in periodic flush (daemonic timer) when configured; default
        # (interval None) keeps the lifecycle explicit-flush-only.
        self._periodic_flusher = setup_periodic_flush(
            self._tracker, self._config.auto_flush_interval_ms
        )

    def _load_raw_config(self) -> Dict[str, Any]:
        if self._config.is_direct_config:
            # Direct config: no transport involved at all (AC #1).
            assert self._config.data is not None  # guaranteed by SDKConfig
            return self._config.data
        return self._fetch_via_transport()

    def _fetch_via_transport(self) -> Dict[str, Any]:
        transport = self._ensure_transport()
        return transport.fetch_config(self._config)

    def _ensure_transport(self) -> "Transport":
        if self._transport is None:
            # Lazy import keeps httpx out of the import path for direct-config
            # initialization.
            from convert_sdk.adapters.transport.httpx_transport import HttpxTransport

            self._transport = HttpxTransport(self._config.transport)
            self._owns_transport = True
        return self._transport

    # --- automatic config refresh (Story 5.2) ------------------------------

    def refresh_now(self) -> None:
        """Trigger an immediate background config refresh, if refresh is enabled.

        A safe no-op when automatic refresh was not opted into (``refresh=None``,
        direct-config mode, or before :meth:`initialize`). The refresh runs on
        the background worker thread and applies through the same atomic swap as
        a scheduled refresh; this call returns immediately without blocking on
        the fetch.
        """
        if self._refresher is not None:
            self._refresher.trigger_now()

    def _apply_refreshed_snapshot(self, snapshot: ConfigSnapshot) -> None:
        """Atomically swap in a refreshed snapshot (ADR 0001).

        The swap is a single mutex-guarded reference rebind so an in-flight
        :meth:`create_context` / :attr:`current_config` read observes either the
        whole previous or the whole new snapshot — never a partial state.
        Snapshots are immutable and replaced wholesale; one is never mutated in
        place (Critical Warning #2).

        After the swap it re-points the shared tracker (and its queue) so
        conversions queued after the refresh attribute to the new project (JS
        parity: ``ApiManager.setData()``), then emits ``CONFIG_UPDATED`` on the
        event bus carrying the new account/project ids and entity counts (the
        JS ``SystemEvents.CONFIG_UPDATED`` analog integrators subscribe to for
        cache busts). Runs on the background worker thread; emission is isolated
        by the bus so a buggy handler never crashes the worker.
        """
        with self._snapshot_lock:
            self._snapshot = snapshot
        if self._tracker is not None:
            self._tracker.update_snapshot(snapshot)
        self._event_bus.emit(
            LifecycleEvent.CONFIG_UPDATED,
            {
                "account_id": snapshot.account_id,
                "project_id": snapshot.project_id,
                "entity_counts": {
                    "experiences": len(snapshot.experiences),
                    "features": len(snapshot.features),
                    "goals": len(snapshot.goals),
                    "audiences": len(snapshot.audiences),
                    "segments": len(snapshot.segments),
                },
            },
        )

    def _refresher_alive(self) -> bool:
        """True while the background refresh worker thread is running (test seam)."""
        return self._refresher is not None and self._refresher.is_alive()

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Release resources. Closes the transport only if Core created it.

        Stops the opt-in background refresh worker (Story 5.2) and cancels the
        opt-in periodic-flush timer (if any) so the daemonic threads stop
        rescheduling. Does NOT perform a final flush — explicit flush and the
        best-effort ``atexit`` hook are the documented shutdown-delivery paths.
        """
        if self._refresher is not None:
            self._refresher.stop()
            self._refresher = None
        if self._periodic_flusher is not None:
            self._periodic_flusher.cancel()
            self._periodic_flusher = None
        if self._transport is not None and self._owns_transport:
            self._transport.close()
            self._transport = None
            self._owns_transport = False

    def __enter__(self) -> "Core":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
