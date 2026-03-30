from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class EventManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        logger_manager: Any | None = None,
    ) -> None:
        config = dict(config or {})
        self._listeners: dict[str, list[Callable[[Any, Any], None]]] = {}
        self._deferred: dict[str, dict[str, Any]] = {}
        self._mapper = config.get("mapper") or (lambda value: value)
        self._logger_manager = logger_manager

    def _event_key(self, event: Any) -> str:
        return getattr(event, "value", event)

    def on(self, event: str, fn: Callable[[Any, Any], None]) -> None:
        event_key = self._event_key(event)
        self._listeners.setdefault(event_key, []).append(fn)
        if event_key in self._deferred:
            deferred = self._deferred[event_key]
            self.fire(event_key, deferred.get("args"), deferred.get("err"))

    def remove_listeners(self, event: str) -> None:
        event_key = self._event_key(event)
        self._listeners.pop(event_key, None)
        self._deferred.pop(event_key, None)

    def fire(
        self,
        event: str,
        args: Any = None,
        err: Any = None,
        deferred: bool = False,
    ) -> None:
        event_key = self._event_key(event)
        listeners = list(self._listeners.get(event_key, []))
        for fn in listeners:
            try:
                fn(self._mapper(args), err)
            except Exception as error:
                if self._logger_manager:
                    self._logger_manager.error("EventManager.fire()", error)
        if deferred and event_key not in self._deferred:
            self._deferred[event_key] = {"args": args, "err": err}
