"""Public SDK entry point for initialization and readiness state."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .adapters.events.in_memory_event_bus import InMemoryEventBus
from .adapters.storage.in_memory import InMemoryDataStore
from .adapters.transport.httpx_transport import HttpxTransport
from .config import SDKConfig
from .config_loader.loader import load_config_snapshot
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
        self._initialize()

    def _initialize(self) -> None:
        self._snapshot = load_config_snapshot(
            self._config,
            transport=self._transport,
        )
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
            if visitor_attributes is None:
                state = self._data_store.load_context_state(visitor_id)
                if state is None:
                    state = ContextState.create(visitor_id=visitor_id)
                    self._data_store.save_context_state(state)
            else:
                state = ContextState.create(
                    visitor_id=visitor_id,
                    visitor_attributes=visitor_attributes,
                )
                self._data_store.save_context_state(state)
        except TypeError as exc:
            raise InitializationError("visitor_attributes must be a mapping") from exc

        return Context(
            snapshot=self._snapshot,
            state=state,
            tracking_queue=self._tracking_queue,
            event_bus=self._event_bus,
            default_environment=self._config.environment,
        )

    def __repr__(self) -> str:
        return f"Core(is_ready={self.is_ready})"
