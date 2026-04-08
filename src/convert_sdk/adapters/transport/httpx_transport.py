"""HTTPX-backed config transport adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from ...ports.transport import ConfigRequest


class HttpxTransport:
    """Sync-first transport adapter for Convert config fetches."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        headers = {"Accept": "application/json"}
        headers.update(dict(request.transport.headers))
        if request.sdk_key_secret:
            headers["Authorization"] = f"Bearer {request.sdk_key_secret}"

        params = {}
        if request.environment:
            params["environment"] = request.environment

        url = (
            f"{request.transport.config_endpoint.rstrip('/')}/config/{request.sdk_key}"
        )

        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=request.transport.timeout_seconds,
            verify=request.transport.verify_tls,
        )
        try:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                client.close()

        if not isinstance(payload, dict):
            raise TypeError("Config endpoint returned a non-object JSON payload")

        return payload
