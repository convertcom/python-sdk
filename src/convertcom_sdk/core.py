from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from convertcom_sdk.errors import DATA_OBJECT_MISSING, SDK_OR_DATA_OBJECT_REQUIRED
from convertcom_sdk.enums import SystemEvents


class Core:
    def __init__(
        self,
        config: Mapping[str, Any] | None,
        *,
        data_manager: Any,
        event_manager: Any,
        experience_manager: Any,
        feature_manager: Any,
        segments_manager: Any,
        api_manager: Any,
    ) -> None:
        self.data: dict[str, Any] | None = None
        self._initialized = False
        self._config = dict(config or {})
        self._data_manager = data_manager
        self._event_manager = event_manager
        self._experience_manager = experience_manager
        self._feature_manager = feature_manager
        self._segments_manager = segments_manager
        self._api_manager = api_manager
        self.initialize(self._config)

    def initialize(self, config: Mapping[str, Any] | None) -> None:
        if not config:
            return
        self._config = dict(config)
        sdk_key = self._config.get("sdkKey")
        has_data = "data" in self._config
        if sdk_key:
            self.refresh_config(initial=True)
        elif has_data:
            data = self._config.get("data") or {}
            self.data = data
            self._data_manager.data = data
            if data.get("error"):
                return
            self._initialized = True
            self._event_manager.fire(SystemEvents.READY, None, None, True)
        else:
            self._event_manager.fire(
                SystemEvents.READY,
                {},
                ValueError(SDK_OR_DATA_OBJECT_REQUIRED),
                True,
            )

    def refresh_config(self, *, initial: bool = False) -> dict[str, Any]:
        data = self._api_manager.get_config()
        if data.get("error"):
            self.data = data
            self._data_manager.data = data
            return data
        had_data = bool(self._data_manager.data)
        self.data = data
        self._data_manager.data = data
        self._api_manager.set_data(data)
        if not had_data and initial:
            self._initialized = True
            self._event_manager.fire(SystemEvents.READY, None, None, True)
        elif had_data:
            self._event_manager.fire(SystemEvents.CONFIG_UPDATED, None, None, True)
        else:
            self._initialized = True
            self._event_manager.fire(SystemEvents.READY, None, None, True)
        return data

    def refreshConfig(self) -> dict[str, Any]:
        return self.refresh_config()

    def create_context(
        self,
        visitor_id: str,
        visitor_attributes: Mapping[str, Any] | None = None,
    ) -> Any | None:
        if not self._initialized:
            return None
        from convertcom_sdk.context import Context

        return Context(
            self._config,
            visitor_id,
            event_manager=self._event_manager,
            experience_manager=self._experience_manager,
            feature_manager=self._feature_manager,
            segments_manager=self._segments_manager,
            data_manager=self._data_manager,
            api_manager=self._api_manager,
            visitor_properties=visitor_attributes,
        )

    def createContext(
        self,
        visitor_id: str,
        visitor_attributes: Mapping[str, Any] | None = None,
    ) -> Any | None:
        return self.create_context(visitor_id, visitor_attributes)

    def on(self, event: str, fn: Callable[[Any, Any], None]) -> None:
        self._event_manager.on(event, fn)

    def on_ready(self) -> None:
        if self._data_manager.data:
            return None
        raise ValueError(DATA_OBJECT_MISSING)

    def onReady(self) -> None:
        return self.on_ready()
