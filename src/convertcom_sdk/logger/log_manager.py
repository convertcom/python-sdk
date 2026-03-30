from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from convertcom_sdk.enums import LogLevel, LogMethod


class _ConsoleProxy:
    def log(self, *args: Any) -> None:
        print(*args)

    def trace(self, *args: Any) -> None:
        print(*args)

    def debug(self, *args: Any) -> None:
        print(*args)

    def info(self, *args: Any) -> None:
        print(*args)

    def warn(self, *args: Any) -> None:
        print(*args)

    def error(self, *args: Any) -> None:
        print(*args)


@dataclass
class LogClient:
    sdk: Any
    level: LogLevel
    mapper: dict[str, str]


class LogManager:
    def __init__(
        self,
        client: Any | None = None,
        level: LogLevel | str = LogLevel.TRACE,
        mapper: dict[str, str] | None = None,
    ) -> None:
        self._clients: list[LogClient] = []
        self._default_mapper = {
            LogMethod.LOG.value: LogMethod.LOG.value,
            LogMethod.DEBUG.value: LogMethod.DEBUG.value,
            LogMethod.INFO.value: LogMethod.INFO.value,
            LogMethod.WARN.value: LogMethod.WARN.value,
            LogMethod.ERROR.value: LogMethod.ERROR.value,
            LogMethod.TRACE.value: LogMethod.TRACE.value,
        }
        self._fallback_client = client or _ConsoleProxy()
        self.add_client(client or _ConsoleProxy(), level, mapper)

    def _normalize_level(self, level: LogLevel | str) -> LogLevel:
        if isinstance(level, LogLevel):
            return level
        if isinstance(level, str):
            return LogLevel[level.upper()]
        raise ValueError("Invalid log level")

    def _log(self, method: LogMethod, level: LogLevel, *args: Any) -> None:
        for client in self._clients:
            if level >= client.level and level != LogLevel.SILENT:
                fn = getattr(client.sdk, client.mapper[method.value], None)
                if callable(fn):
                    fn(*args)
                else:
                    fallback = getattr(self._fallback_client, method.value, None)
                    if callable(fallback):
                        fallback(*args)

    def log(self, level: LogLevel | str, *args: Any) -> None:
        self._log(LogMethod.LOG, self._normalize_level(level), *args)

    def trace(self, *args: Any) -> None:
        self._log(LogMethod.TRACE, LogLevel.TRACE, *args)

    def debug(self, *args: Any) -> None:
        self._log(LogMethod.DEBUG, LogLevel.DEBUG, *args)

    def info(self, *args: Any) -> None:
        self._log(LogMethod.INFO, LogLevel.INFO, *args)

    def warn(self, *args: Any) -> None:
        self._log(LogMethod.WARN, LogLevel.WARN, *args)

    def error(self, *args: Any) -> None:
        self._log(LogMethod.ERROR, LogLevel.ERROR, *args)

    def add_client(
        self,
        client: Any | None = None,
        level: LogLevel | str = LogLevel.TRACE,
        method_map: dict[str, str] | None = None,
    ) -> None:
        if client is None:
            raise ValueError("Invalid client SDK")
        normalized_level = self._normalize_level(level)
        mapper = dict(self._default_mapper)
        if method_map:
            for method, mapped_method in method_map.items():
                if method in mapper:
                    mapper[method] = mapped_method
        self._clients.append(LogClient(client, normalized_level, mapper))

    def addClient(
        self,
        client: Any | None = None,
        level: LogLevel | str = LogLevel.TRACE,
        methodMap: dict[str, str] | None = None,
    ) -> None:
        self.add_client(client, level, methodMap)

    def set_client_level(self, level: LogLevel | str, client: Any | None = None) -> None:
        normalized_level = self._normalize_level(level)
        if client is None:
            for item in self._clients:
                item.level = normalized_level
            return
        for item in self._clients:
            if item.sdk is client:
                item.level = normalized_level
                return
        raise ValueError("Client SDK not found")

    def setClientLevel(self, level: LogLevel | str, client: Any | None = None) -> None:
        self.set_client_level(level, client)
