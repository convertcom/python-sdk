"""httpx-backed transport adapter for the Convert Python SDK (Story 1.2).

Fetches the raw config payload from ``GET /api/v1/config/{sdkKey}`` over HTTPS
using a long-lived :class:`httpx.Client`. The full endpoint is the combination
of ``TransportConfig.base_url`` (a pure host, e.g.
``https://cdn-4.convertexperiments.com``) and the route ``/api/v1/config/{sdkKey}``
built by :meth:`HttpxTransport._build_route`. The ``/api/v1`` prefix is confirmed
by the real Convert config-serving CDN and matches the PHP SDK's generated client
(``ProjectConfigApi``, server base ``https://cdn-4.convertexperiments.com/api/v1``,
resource path ``/config/{sdkKey}``).

Two optional query parameters are appended conditionally:

* ``environment={environment}`` — present only when a non-default environment
  is configured.
* ``_conv_low_cache=1`` — present only when the cache level is ``"low"``.

These parameters mirror the query shape used by the JS SDK. The JS implementation
concatenates the two parameters without a separator (producing
``?environment=prod_conv_low_cache=1``). This adapter preserves the *intent*
(both parameters present, conditionally) while emitting a well-formed, parseable
query string (parameters joined with ``&``) — see the Story 1.2 readiness note.
Tests assert presence/absence of each parameter, not the malformed concatenation.

TLS-only transport (NFR8) is enforced upstream at
:class:`~convert_sdk.config.TransportConfig` construction; an insecure base URL
can never reach this adapter. Optional bearer auth is injected as an
``Authorization`` header. All HTTP/transport/decode failures surface as a typed
:class:`~convert_sdk.errors.ConfigLoadError` with a redacted endpoint and status
code (NFR23 / qs-08 shim).

Tracking events are delivered to a SEPARATE metrics endpoint, NOT the config CDN:

    ``POST {track_base}/track/{sdkKey}``

where ``track_base`` is ``TransportConfig.track_base_url`` with the
``[project_id]`` placeholder substituted with the real project id read from the
payload's ``projectId`` field (JS parity: api-manager.ts line 224-228; PHP
parity: ApiManager.php line 322). Every tracking POST also sets the header::

    ``User-Agent: ConvertAgent/1.0``

so the metrics endpoint's bot filter (``isConvertAgentUA`` bypass) recognises
Convert SDK traffic and does NOT silently drop events. Both JS
(http-client.ts:16 ``CONVERT_AGENT_USER_AGENT = 'ConvertAgent/1.0'``) and PHP
(ApiManager.php:64 ``private const CONVERT_AGENT_USER_AGENT = 'ConvertAgent/1.0'``)
set this header on every tracking request.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from convert_sdk._internal.redaction import redact_url
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
        route = f"/api/v1/config/{config.sdk_key}"
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

    # --- tracking delivery (metrics host) ------------------------------------

    #: User-Agent required by the metrics-endpoint bot filter to recognise
    #: Convert SDK traffic via its ``isConvertAgentUA`` bypass. Must start with
    #: ``ConvertAgent/``. JS parity: http-client.ts:16; PHP parity:
    #: ApiManager.php:64.
    _CONVERT_AGENT_USER_AGENT = "ConvertAgent/1.0"

    @staticmethod
    def _build_track_url(track_base_url: str, project_id: str, sdk_key: str) -> str:
        """Resolve the absolute tracking URL for this request.

        Substitutes ``[project_id]`` with the real project id in the
        ``track_base_url`` template (JS parity: api-manager.ts line 224-228;
        PHP parity: ApiManager.php line 322), then appends the
        ``/track/{sdkKey}`` route segment.
        """
        resolved_base = track_base_url.replace("[project_id]", project_id)
        return f"{resolved_base}/track/{sdk_key}"

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> int:
        """POST a serialized tracking-events batch to the metrics endpoint.

        Tracking events are delivered to a SEPARATE metrics endpoint:

            ``POST {track_base}/track/{sdkKey}``

        where ``track_base`` is ``TransportConfig.track_base_url`` with the
        ``[project_id]`` placeholder substituted from ``payload["projectId"]``.
        This is the JS/PHP SDK behavior — tracking MUST NOT go to the config
        CDN host (the CDN returns 403 for tracking POSTs).

        Also sets ``User-Agent: ConvertAgent/1.0`` so the metrics endpoint's bot
        filter recognises Convert SDK traffic and does NOT silently drop events
        (the bot filter returns 200 OK but discards events lacking this UA).

        Returns the HTTP status code (int, e.g. 200) on a successful delivery
        so the caller can populate ``QueueReleasedPayload.status_code`` on the
        success path.

        Performs NO retry/backoff — the tracking layer calls this exactly once
        per queue release. Any transport/HTTP failure raises a typed
        :class:`~convert_sdk.errors.TrackingDeliveryError` with a redacted
        endpoint (NFR23).
        """
        project_id = str(payload.get("projectId", ""))
        track_url = self._build_track_url(
            self._config.track_base_url, project_id, sdk_key
        )
        # Redacted endpoint for error messages — query-string-free host+path
        # with SDK key masked (NFR23 / qs-08).
        redacted_endpoint = redact_url(track_url) or track_url
        tracking_headers = {
            "User-Agent": self._CONVERT_AGENT_USER_AGENT,
        }
        try:
            response = self._client.post(
                track_url, json=payload, headers=tracking_headers
            )
        except httpx.HTTPError as exc:  # connection/timeout/etc.
            raise TrackingDeliveryError(
                f"tracking delivery failed: {type(exc).__name__}",
                endpoint=redacted_endpoint,
            ) from exc

        if response.status_code >= 400:
            raise TrackingDeliveryError(
                "tracking delivery returned an error status",
                endpoint=redacted_endpoint,
                status_code=response.status_code,
            )

        return response.status_code

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxTransport":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
