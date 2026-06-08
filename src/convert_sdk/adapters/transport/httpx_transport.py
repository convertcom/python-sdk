"""httpx-backed transport adapter for the Convert Python SDK (Story 1.2).

Fetches the raw config payload from ``GET /config/{sdkKey}`` over HTTPS using a
long-lived :class:`httpx.Client`. The query string follows JS SDK parity
(``javascript-sdk/packages/api/src/api-manager.ts`` ``getConfig()``):

* ``environment={environment}`` is appended only when a non-default environment
  is configured.
* ``_conv_low_cache=1`` is appended only when the cache level is ``"low"``.

The JS implementation concatenates the two parameters without a separator
(producing ``?environment=prod_conv_low_cache=1``). This adapter preserves the
*intent* (both parameters present, conditionally) while emitting a well-formed,
parseable query string (parameters joined with ``&``) — see the Story 1.2
readiness note. Tests assert presence/absence of each parameter, not the
malformed concatenation.

TLS-only transport (NFR8) is enforced upstream at
:class:`~convert_sdk.config.TransportConfig` construction; an insecure base URL
can never reach this adapter. Optional bearer auth is injected as an
``Authorization`` header. All HTTP/transport/decode failures surface as a typed
:class:`~convert_sdk.errors.ConfigLoadError` with a redacted endpoint and status
code (NFR23 / qs-08 shim).
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.errors import ConfigLoadError, TrackingDeliveryError


class HttpxTransport:
    """Long-lived httpx-backed implementation of the transport port."""

    def __init__(
        self,
        transport_config: TransportConfig,
        *,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._config = transport_config
        headers: Dict[str, str] = dict(transport_config.headers)
        if transport_config.auth_secret:
            headers["Authorization"] = f"Bearer {transport_config.auth_secret}"
        # A single long-lived client is preferred over one-off request helpers.
        # trust_env=False makes config fetches deterministic: the SDK does not
        # implicitly inherit ambient proxy/SSL environment variables (e.g. a
        # host SOCKS proxy). Explicit transport configuration remains available
        # for proxied deployments.
        self._client = client or httpx.Client(
            base_url=transport_config.base_url,
            timeout=transport_config.timeout,
            verify=transport_config.verify_tls,
            headers=headers,
            trust_env=False,
        )

    # --- query construction (JS parity) ------------------------------------

    @staticmethod
    def _build_query(config: SDKConfig) -> str:
        params = []
        if config.environment:
            params.append(("environment", config.environment))
        if config.cache_level == "low":
            params.append(("_conv_low_cache", "1"))
        return urlencode(params) if params else ""

    @staticmethod
    def _build_route(config: SDKConfig) -> str:
        query = HttpxTransport._build_query(config)
        route = f"/config/{config.sdk_key}"
        return f"{route}?{query}" if query else route

    # --- transport port ----------------------------------------------------

    def fetch_config(self, config: SDKConfig) -> Dict[str, Any]:
        route = self._build_route(config)
        # Endpoint used only for diagnostics; ConfigLoadError redacts the query.
        endpoint = f"{self._config.base_url}{route}"
        try:
            response = self._client.get(route)
        except httpx.HTTPError as exc:  # connection/timeout/etc.
            raise ConfigLoadError(
                f"config fetch failed: {type(exc).__name__}",
                endpoint=endpoint,
            ) from exc

        if response.status_code >= 400:
            raise ConfigLoadError(
                "config fetch returned an error status",
                endpoint=endpoint,
                status_code=response.status_code,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ConfigLoadError(
                "config response body was not valid JSON",
                endpoint=endpoint,
                status_code=response.status_code,
            ) from exc

        if not isinstance(body, dict):
            raise ConfigLoadError(
                "config response body was not a JSON object",
                endpoint=endpoint,
                status_code=response.status_code,
            )
        return body

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> None:
        """POST a serialized tracking-events batch to ``/track/{sdkKey}`` (Story 2.3).

        Delivers over the long-lived HTTPS client (TLS-only is enforced upstream
        at :class:`~convert_sdk.config.TransportConfig` construction). Performs
        NO retry/backoff — the tracking layer calls this exactly once per queue
        release. Any transport/HTTP failure (connection error or non-2xx status)
        raises a typed :class:`~convert_sdk.errors.TrackingDeliveryError` with a
        redacted endpoint so the caller can leave the queue intact for a later
        flush, without leaking the SDK key or query string (NFR23).
        """
        route = f"/track/{sdk_key}"
        endpoint = f"{self._config.base_url}{route}"
        try:
            response = self._client.post(route, json=payload)
        except httpx.HTTPError as exc:  # connection/timeout/etc.
            raise TrackingDeliveryError(
                f"tracking delivery failed: {type(exc).__name__}",
                endpoint=endpoint,
            ) from exc

        if response.status_code >= 400:
            raise TrackingDeliveryError(
                "tracking delivery returned an error status",
                endpoint=endpoint,
                status_code=response.status_code,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxTransport":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
