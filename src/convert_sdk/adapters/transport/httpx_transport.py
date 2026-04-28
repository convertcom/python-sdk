"""HTTPX-backed config and tracking transport adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import quote

import httpx

from ...ports.transport import ConfigRequest, TrackingRequest


# Headers the SDK sets to enforce its wire contract; user-supplied
# ``TransportConfig.headers`` cannot override these. Allowing user
# override of ``Content-Type`` would silently break tracking POSTs
# (the body remains JSON regardless), and overriding ``Authorization``
# would defeat the SDK key secret semantics. The SDK still adds the
# user-supplied ``headers`` dict for everything else (custom proxy
# routing, observability tags, etc.).
_RESERVED_HEADERS = frozenset({"authorization", "content-type"})


def _merge_headers(
    sdk_defaults: Mapping[str, str],
    user_headers: Mapping[str, str],
) -> dict[str, str]:
    headers: dict[str, str] = dict(sdk_defaults)
    for key, value in user_headers.items():
        if key.lower() in _RESERVED_HEADERS:
            # Silently ignore reserved-header overrides rather than
            # let users break the wire contract.
            continue
        headers[key] = value
    return headers


def _safe_route_segment(value: str) -> str:
    # The SDK key (or account/project pair) is interpolated into the
    # URL path; without quoting, ``/``, ``?``, ``#``, or whitespace in
    # the value silently produces a different URL or a path traversal.
    # ``safe=""`` quotes everything except unreserved characters.
    return quote(value, safe="")


class HttpxTransport:
    """Sync-first transport adapter for Convert config fetches and tracking."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        # When ``client`` is None, a long-lived ``httpx.Client`` is
        # created lazily on first use and reused across requests. This
        # matters for auto-refresh and high-throughput tracking — a
        # fresh client per call would pay a full TLS handshake every
        # time. Call ``close()`` on the adapter (or ``Core.close()``)
        # to release the lazily-created client.
        self._client = client
        self._owns_client = client is None
        self._lazy_client: Optional[httpx.Client] = None

    def _get_client(self, *, timeout: float, verify: bool) -> httpx.Client:
        if self._client is not None:
            return self._client
        if self._lazy_client is None:
            self._lazy_client = httpx.Client(timeout=timeout, verify=verify)
        return self._lazy_client

    def close(self) -> None:
        """Release the lazily-created client, if any."""

        if self._lazy_client is not None:
            try:
                self._lazy_client.close()
            finally:
                self._lazy_client = None

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        sdk_defaults = {"Accept": "application/json"}
        if request.sdk_key_secret:
            sdk_defaults["Authorization"] = f"Bearer {request.sdk_key_secret}"
        headers = _merge_headers(sdk_defaults, request.transport.headers)

        params = {}
        if request.environment:
            params["environment"] = request.environment

        sdk_key_segment = _safe_route_segment(request.sdk_key or "")
        url = (
            f"{request.transport.config_endpoint.rstrip('/')}/config/{sdk_key_segment}"
        )

        client = self._get_client(
            timeout=request.transport.timeout_seconds,
            verify=request.transport.verify_tls,
        )
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise TypeError("Config endpoint returned a non-object JSON payload")

        return payload

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        sdk_defaults = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if request.sdk_key_secret:
            sdk_defaults["Authorization"] = f"Bearer {request.sdk_key_secret}"
        headers = _merge_headers(sdk_defaults, request.transport.headers)

        if request.sdk_key:
            route = _safe_route_segment(request.sdk_key)
        elif request.account_id and request.project_id:
            route = (
                f"{_safe_route_segment(request.account_id)}/"
                f"{_safe_route_segment(request.project_id)}"
            )
        else:
            raise ValueError(
                "Tracking delivery requires sdk_key or account_id/project_id"
            )

        url = f"{request.transport.tracking_endpoint.rstrip('/')}/track/{route}"

        client = self._get_client(
            timeout=request.transport.timeout_seconds,
            verify=request.transport.verify_tls,
        )
        response = client.post(url, json=dict(request.payload), headers=headers)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()

        if not isinstance(payload, dict):
            raise TypeError("Tracking endpoint returned a non-object JSON payload")

        return payload
