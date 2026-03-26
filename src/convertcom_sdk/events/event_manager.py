from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class EventManager:
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        config = dict(config or {})
        self._listeners: dict[str, list[Callable[[Any, Any], None]]] = {}
        self._deferred: dict[str, dict[str, Any]] = {}
        self._mapper = config.get("mapper") or (lambda value: value)

    def on(self, event: str, fn: Callable[[Any, Any], None]) -> None:
        self._listeners.setdefault(str(event), []).append(fn)
        if str(event) in self._deferred:
            deferred = self._deferred[str(event)]
            self.fire(str(event), deferred.get("args"), deferred.get("err"))

    def remove_listeners(self, event: str) -> None:
        self._listeners.pop(str(event), None)
        self._deferred.pop(str(event), None)

    def fire(
        self,
        event: str,
        args: Any = None,
        err: Any = None,
        deferred: bool = False,
    ) -> None:
        listeners = list(self._listeners.get(str(event), []))
        for fn in listeners:
            fn(self._mapper(args), err)
        if deferred and str(event) not in self._deferred:
            self._deferred[str(event)] = {"args": args, "err": err}
