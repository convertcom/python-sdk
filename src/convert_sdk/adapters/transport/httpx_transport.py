"""HTTPX-backed config and tracking transport adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from ...ports.transport import ConfigRequest, TrackingRequest


class HttpxTransport:
    """Sync-first transport adapter for Convert config fetches and tracking."""

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

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        headers.update(dict(request.transport.headers))
        if request.sdk_key_secret:
            headers["Authorization"] = f"Bearer {request.sdk_key_secret}"

        if request.sdk_key:
            route = request.sdk_key
        elif request.account_id and request.project_id:
            route = f"{request.account_id}/{request.project_id}"
        else:
            raise ValueError(
                "Tracking delivery requires sdk_key or account_id/project_id"
            )

        url = f"{request.transport.tracking_endpoint.rstrip('/')}/track/{route}"

        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=request.transport.timeout_seconds,
            verify=request.transport.verify_tls,
        )
        try:
            response = client.post(url, json=dict(request.payload), headers=headers)
            response.raise_for_status()
            if not response.content:
                return {}
            payload = response.json()
        finally:
            if owns_client:
                client.close()

        if not isinstance(payload, dict):
            raise TypeError("Tracking endpoint returned a non-object JSON payload")

        return payload
