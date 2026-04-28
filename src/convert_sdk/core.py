"""Public SDK entry point for initialization and readiness state."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Mapping, Optional, Type

from .adapters.events.in_memory_event_bus import InMemoryEventBus
from .adapters.storage.in_memory import InMemoryDataStore
from .adapters.transport.httpx_transport import HttpxTransport
from .config import SDKConfig
from .config_loader.loader import load_config_snapshot
from .config_loader.refresh import ConfigRefresher
from .diagnostics import config_source, log_diagnostic_event, snapshot_entity_counts
from .context import Context
from .domain.config_snapshot import ConfigSnapshot
from .domain.context_state import ContextState
from .errors import InitializationError
from .events import LifecycleEvent
from .ports.event_bus import EventBus, EventHandler
from .ports.storage import DataStore
from .ports.transport import Transport
from .tracking.queue import TrackingQueue


class Core:
    """Stable root export for SDK initialization and config access."""

    def __init__(
        self,
        config: SDKConfig,
        transport: Optional[Transport] = None,
        data_store: Optional[DataStore] = None,
    ) -> None:
        self._config = config
        self._snapshot: Optional[ConfigSnapshot] = None
        self._transport = transport or HttpxTransport()
        self._data_store = data_store or InMemoryDataStore()
        self._event_bus: EventBus = InMemoryEventBus()
        self._tracking_queue: Optional[TrackingQueue] = None
        self._refresher: Optional[ConfigRefresher] = None
        self._closed = False
        self._initialize()
        self._maybe_start_refresher()

    def _initialize(self) -> None:
        source = config_source(self._config.config_data, self._config.sdk_key)
        log_diagnostic_event(
            "sdk.initialization.started",
            source=source,
            has_environment=bool(self._config.environment),
            transport_type=type(self._transport).__name__,
            data_store_type=type(self._data_store).__name__,
        )
        try:
            self._snapshot = load_config_snapshot(
                self._config,
                transport=self._transport,
            )
        except Exception as exc:
            log_diagnostic_event(
                "sdk.initialization.failed",
                level=logging.WARNING,
                source=source,
                error_type=type(exc).__name__,
                error_code=getattr(exc, "code", None),
            )
            raise
        self._tracking_queue = TrackingQueue(
            transport=self._transport,
            transport_config=self._config.transport,
            tracking_config=self._config.tracking,
            sdk_key=self._config.sdk_key,
            sdk_key_secret=self._config.sdk_key_secret,
            account_id=self._snapshot.account_id,
            project_id=self._snapshot.project_id,
            event_bus=self._event_bus,
            data_store=self._data_store,
        )
        log_diagnostic_event(
            "sdk.initialization.succeeded",
            source=source,
            is_ready=self.is_ready,
            has_account_id=self._snapshot.account_id is not None,
            has_project_id=self._snapshot.project_id is not None,
            entity_counts=snapshot_entity_counts(self._snapshot),
        )

    def _maybe_start_refresher(self) -> None:
        if self._config.refresh is None:
            return
        if self._config.config_data is not None:
            # Direct-config mode has no remote endpoint; an opt-in refresh
            # policy here is almost certainly a misconfiguration. Surface
            # it through diagnostics rather than silently ignoring.
            log_diagnostic_event(
                "refresh.skipped",
                source=config_source(self._config.config_data, self._config.sdk_key),
                reason="direct_config_no_remote_endpoint",
            )
            return
        self._refresher = ConfigRefresher(
            self._config,
            transport=self._transport,
            apply_snapshot=self._apply_refreshed_snapshot,
            current_snapshot=lambda: self._snapshot,
        )
        self._refresher.start()

    def _apply_refreshed_snapshot(self, snapshot: ConfigSnapshot) -> None:
        # Order matters: refresh the tracking queue's ids first so a reader
        # that loads the new snapshot pointer can never observe stale
        # account/project ids. The snapshot pointer flip itself is atomic
        # in CPython (single attribute assignment), so an in-flight
        # evaluation reads either the prior or the new snapshot — never a
        # partial state. Mirrors JS SDK's ApiManager.setData() coupling.
        if self._tracking_queue is not None:
            self._tracking_queue.update_snapshot_metadata(
                account_id=snapshot.account_id,
                project_id=snapshot.project_id,
            )
        self._snapshot = snapshot
        self._event_bus.emit(
            LifecycleEvent.CONFIG_UPDATED,
            account_id=snapshot.account_id,
            project_id=snapshot.project_id,
            entity_counts=dict(snapshot_entity_counts(snapshot)),
        )

    @property
    def config(self) -> SDKConfig:
        """Return the initialization config used for the SDK instance."""

        return self._config

    @property
    def is_ready(self) -> bool:
        """Return whether the SDK has a current immutable config snapshot."""

        return self._snapshot is not None

    @property
    def snapshot(self) -> ConfigSnapshot:
        """Expose the current immutable config snapshot."""

        if self._snapshot is None:
            raise RuntimeError("Core is not ready")
        return self._snapshot

    @property
    def current_snapshot(self) -> ConfigSnapshot:
        """Alias for the current immutable config snapshot."""

        return self.snapshot

    def on(self, event: LifecycleEvent | str, handler: EventHandler) -> None:
        """Subscribe to a lifecycle event."""

        self._event_bus.subscribe(LifecycleEvent(event), handler)

    def off(self, event: LifecycleEvent | str, handler: EventHandler) -> None:
        """Unsubscribe from a lifecycle event."""

        self._event_bus.unsubscribe(LifecycleEvent(event), handler)

    def refresh_now(self) -> None:
        """Trigger an immediate config refresh attempt (no-op if disabled)."""

        if self._refresher is None:
            return
        self._refresher.trigger_now()

    def close(self) -> None:
        """Stop background workers and release transport resources.

        Safe to call multiple times. After ``close()`` the SDK instance
        should not be reused: existing ``Context`` objects retain the
        last-applied snapshot but no further refresh attempts run and
        no further tracking deliveries are permitted.
        """

        if self._closed:
            return
        self._closed = True
        if self._refresher is not None:
            self._refresher.stop()
            self._refresher = None
        # Best-effort transport cleanup; not all transports expose close.
        close = getattr(self._transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                _logger = logging.getLogger("convert_sdk")
                _logger.exception("transport close failed; suppressing during Core.close()")

    def __enter__(self) -> "Core":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def create_context(
        self,
        visitor_id: str,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
    ) -> Context:
        """Create a reusable per-visitor context from the current snapshot."""

        if not isinstance(visitor_id, str) or not visitor_id.strip():
            raise InitializationError("visitor_id is required to create a Context")
        if self._snapshot is None or self._tracking_queue is None:
            raise InitializationError("Core is not ready")

        try:
            existing_state = self._data_store.load_context_state(visitor_id)
            if visitor_attributes is None:
                state = existing_state
                if state is None:
                    state = ContextState.create(visitor_id=visitor_id)
                    self._data_store.save_context_state(state)
            else:
                state = ContextState.create(
                    visitor_id=visitor_id,
                    visitor_attributes=visitor_attributes,
                    visitor_properties=(
                        existing_state.visitor_properties
                        if existing_state is not None
                        else None
                    ),
                    default_segments=(
                        existing_state.default_segments
                        if existing_state is not None
                        else None
                    ),
                )
                self._data_store.save_context_state(state)
        except TypeError as exc:
            raise InitializationError("visitor_attributes must be a mapping") from exc

        log_diagnostic_event(
            "context.created",
            visitor_id=visitor_id,
            had_existing_state=existing_state is not None,
            supplied_visitor_attribute_count=(
                len(visitor_attributes) if visitor_attributes is not None else 0
            ),
            stored_visitor_attribute_count=len(state.visitor_attributes),
            stored_visitor_property_count=len(state.visitor_properties),
            default_segment_count=len(state.default_segments),
        )
        return Context(
            snapshot=self._snapshot,
            state=state,
            tracking_queue=self._tracking_queue,
            event_bus=self._event_bus,
            data_store=self._data_store,
            default_environment=self._config.environment,
        )

    def __repr__(self) -> str:
        return f"Core(is_ready={self.is_ready})"
