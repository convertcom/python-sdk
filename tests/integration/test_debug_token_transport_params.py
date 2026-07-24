"""PY-1 (RED) — qs-02 AC1/AC2: debug_token propagation + token hygiene.

Covers the two integration-level slices of the debug_token contract that the
unit-level ``test_httpx_transport.py`` tests cannot exercise on their own:

* AC1 — the automatic-refresh loop (``RefreshConfig`` + ``core.refresh_now()``)
  fetches config through the SAME ``SDKConfig`` instance as the initial load,
  so a triggered refresh's GET must carry the identical ``debug_token`` +
  forced ``_conv_low_cache=1`` query params as the initial fetch.
* AC2 — the token must never leak into a tracking POST (a separate metrics
  endpoint, built from ``track_base_url`` — the config query is never
  consulted for that request) nor into the serialized tracking payload body.

All HTTP is mocked at the RESPX route level via the shared qs-06 integration
harness (``tests/integration/conftest.py``) — no real network.
"""

from __future__ import annotations

import httpx

from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import RefreshConfig, SDKConfig, TransportConfig
from convert_sdk.core import Core

from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL, SDK_KEY

_DEBUG_TOKEN = "preview-tok-xyz789"


def _remote_core_with_debug_token(*, transport, refresh=None) -> Core:
    config = SDKConfig(
        sdk_key=SDK_KEY,
        debug_token=_DEBUG_TOKEN,
        transport=TransportConfig(
            base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
        ),
        refresh=refresh,
    )
    return Core(config, transport=transport)


def test_refresh_now_fetch_carries_debug_token_and_forced_low_cache(
    respx_mock, minimal_config
):
    """AC1: a refresh-triggered fetch inherits the same debug_token + forced
    _conv_low_cache=1 params as the initial load, because both call sites read
    the same frozen SDKConfig through HttpxTransport._build_route."""
    route = respx_mock.get(f"/api/v1/config/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json=minimal_config)
    )
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core_with_debug_token(
        transport=transport, refresh=RefreshConfig(interval_seconds=300)
    )
    core.initialize()
    try:
        assert route.call_count == 1
        initial_request = route.calls[-1].request
        assert initial_request.url.params.get("debug_token") == _DEBUG_TOKEN
        assert initial_request.url.params.get("_conv_low_cache") == "1"

        core.refresh_now()
        assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]

        assert route.call_count == 2
        refresh_request = route.calls[-1].request
        assert refresh_request.url.params.get("debug_token") == _DEBUG_TOKEN
        assert refresh_request.url.params.get("_conv_low_cache") == "1"
    finally:
        core.close()


def test_debug_token_absent_from_tracking_request_url_and_body(
    respx_mock, mock_config_endpoint, mock_tracking_endpoint
):
    """AC2: the token never appears in a track request — tracking POSTs to a
    separate metrics endpoint built from track_base_url; the config query
    (where debug_token lives) is never consulted for that request."""
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = _remote_core_with_debug_token(transport=transport)
    core.initialize()
    try:
        core.create_context("visitor-1").track_conversion("purchase_completed")
        core.flush()

        assert mock_tracking_endpoint.call_count == 1
        tracked_request = mock_tracking_endpoint.calls.last.request
        assert _DEBUG_TOKEN not in str(tracked_request.url)
        assert _DEBUG_TOKEN not in tracked_request.content.decode("utf-8")
    finally:
        core.close()
