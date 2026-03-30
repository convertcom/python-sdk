from __future__ import annotations

import copy
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from convertcom_sdk.enums import SystemEvents
from convertcom_sdk.utils.http_client import HttpResponse, request as http_request

DEFAULT_HEADERS = {"Content-Type": "application/json"}
DEFAULT_BATCH_SIZE = 10
DEFAULT_RELEASE_INTERVAL = 10000
DEFAULT_CONFIG_ENDPOINT = os.getenv("CONFIG_ENDPOINT", "")
DEFAULT_TRACK_ENDPOINT = os.getenv("TRACK_ENDPOINT", "")


@dataclass
class VisitorQueueItem:
    visitorId: str
    events: list[dict[str, Any]] = field(default_factory=list)
    segments: dict[str, Any] | None = None


class VisitorsQueue:
    def __init__(self) -> None:
        self.length = 0
        self.items: list[VisitorQueueItem] = []

    def push(
        self,
        visitor_id: str,
        event_request: Mapping[str, Any],
        segments: Mapping[str, Any] | None = None,
    ) -> None:
        for item in self.items:
            if item.visitorId == visitor_id:
                item.events.append(dict(event_request))
                self.length += 1
                return
        self.items.append(
            VisitorQueueItem(
                visitorId=visitor_id,
                events=[dict(event_request)],
                segments=dict(segments) if segments else None,
            )
        )
        self.length += 1

    def reset(self) -> None:
        self.items = []
        self.length = 0


class ApiManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        event_manager: Any | None = None,
        request_sender: Callable[..., HttpResponse] | None = None,
    ) -> None:
        config = dict(config or {})
        self._lock = threading.RLock()
        self._event_manager = event_manager
        self._request_sender = request_sender or http_request
        endpoints = ((config.get("api") or {}).get("endpoint")) or {}
        network = config.get("network") or {}
        events = config.get("events") or {}
        self._data = dict(config.get("data") or {})
        self._enrich_data = not bool(config.get("dataStore"))
        self._environment = config.get("environment")
        self._mapper = config.get("mapper") or (lambda value: value)
        self._config_endpoint = endpoints.get("config") or DEFAULT_CONFIG_ENDPOINT
        self._track_endpoint = endpoints.get("track") or DEFAULT_TRACK_ENDPOINT
        self._default_headers = dict(DEFAULT_HEADERS)
        self.batch_size = int(events.get("batch_size") or DEFAULT_BATCH_SIZE)
        self.release_interval = int(
            events.get("release_interval") or DEFAULT_RELEASE_INTERVAL
        )
        self._account_id = self._data.get("account_id")
        self._project_id = (self._data.get("project") or {}).get("id")
        self._sdk_key = config.get("sdkKey") or self._build_default_sdk_key()
        if config.get("sdkKeySecret"):
            self._default_headers["Authorization"] = (
                f"Bearer {config['sdkKeySecret']}"
            )
        self._tracking_event = {
            "enrichData": self._enrich_data,
            "accountId": self._account_id,
            "projectId": self._project_id,
            "visitors": [],
        }
        self._tracking_enabled = bool(network.get("tracking"))
        self._tracking_source = network.get("source") or "python-sdk"
        self._cache_level = network.get("cacheLevel")
        self._request_timeout = float(network.get("requestTimeout") or 10.0)
        self._config_retries = int(network.get("configRetries") or 0)
        self._track_retries = int(network.get("trackRetries") or 0)
        self._retry_backoff = float(network.get("retryBackoff") or 0.0)
        self._requests_queue = VisitorsQueue()
        self._requests_queue_timer: threading.Timer | None = None

    def _build_default_sdk_key(self) -> str:
        if self._account_id and self._project_id:
            return f"{self._account_id}/{self._project_id}"
        return ""

    def request(
        self,
        method: str,
        path: Mapping[str, str],
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        *,
        retries: int | None = None,
    ) -> HttpResponse:
        request_headers = {
            **self._default_headers,
            **dict(headers or {}),
        }
        resolved_retries = retries
        if resolved_retries is None:
            resolved_retries = (
                self._config_retries if method.lower() == "get" else self._track_retries
            )
        return self._request_sender(
            method=method,
            base_url=path["base"],
            route=path["route"],
            headers=request_headers,
            data=dict(data or {}),
            timeout=self._request_timeout,
            retries=resolved_retries,
            retry_backoff=self._retry_backoff,
        )

    def enqueue(
        self,
        visitor_id: str,
        event_request: Mapping[str, Any],
        segments: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._requests_queue.push(visitor_id, event_request, segments)
            queue_length = self._requests_queue.length
            tracking_enabled = self._tracking_enabled
        if tracking_enabled:
            if queue_length == 1:
                self.start_queue()
            elif queue_length == self.batch_size:
                self.release_queue("size")

    def release_queue(self, reason: str | None = None) -> HttpResponse | None:
        with self._lock:
            if not self._requests_queue.length:
                return None
            self.stop_queue()
            payload = dict(self._tracking_event)
            payload["visitors"] = [
                {
                    "visitorId": item.visitorId,
                    "events": copy.deepcopy(item.events),
                    **({"segments": copy.deepcopy(item.segments)} if item.segments else {}),
                }
                for item in self._requests_queue.items
            ]
            payload["source"] = self._tracking_source
        try:
            response = self.request(
                "post",
                {
                    "base": self._track_endpoint.replace(
                        "[project_id]", str(self._project_id or "")
                    ),
                    "route": f"/track/{self._sdk_key}",
                },
                self._mapper(payload),
            )
        except Exception as error:
            self.start_queue()
            if self._event_manager:
                self._event_manager.fire(
                    SystemEvents.API_QUEUE_RELEASED,
                    {"reason": reason},
                    error,
                )
            return None

        with self._lock:
            self._requests_queue.reset()
        if self._event_manager:
            self._event_manager.fire(
                SystemEvents.API_QUEUE_RELEASED,
                {"reason": reason, "result": response, "visitors": payload["visitors"]},
                None,
            )
        return response

    def stop_queue(self) -> None:
        with self._lock:
            timer = self._requests_queue_timer
            self._requests_queue_timer = None
        if timer:
            timer.cancel()

    def start_queue(self) -> None:
        self.stop_queue()
        with self._lock:
            timer = threading.Timer(
                self.release_interval / 1000.0,
                lambda: self.release_queue("timeout"),
            )
            timer.daemon = True
            self._requests_queue_timer = timer
            timer.start()

    def enable_tracking(self) -> None:
        self._tracking_enabled = True
        self.release_queue("trackingEnabled")

    def disable_tracking(self) -> None:
        self._tracking_enabled = False

    def set_data(self, data: Mapping[str, Any] | None) -> None:
        self._data = dict(data or {})
        self._account_id = self._data.get("account_id")
        self._project_id = (self._data.get("project") or {}).get("id")
        self._tracking_event["accountId"] = self._account_id
        self._tracking_event["projectId"] = self._project_id
        if not self._sdk_key:
            self._sdk_key = self._build_default_sdk_key()

    def get_config(self) -> dict[str, Any]:
        query = "?" if self._cache_level == "low" or self._environment else ""
        if self._environment:
            query += f"environment={self._environment}"
        if self._cache_level == "low":
            query += ("&" if self._environment else "") + "_conv_low_cache=1"
        response = self.request(
            "get",
            {
                "base": self._config_endpoint,
                "route": f"/config/{self._sdk_key}{query}",
            },
            retries=self._config_retries,
        )
        return dict(response.data or {})

    def close(self) -> None:
        self.stop_queue()
