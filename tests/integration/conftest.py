"""Shared integration-test harness (qs-06 — frozen fixtures).

Provides RESPX route-level fixtures and adapter factories so individual
integration tests focus on behavior assertions, not setup. Per qs-06
#Boundaries-and-Constraints:

* All HTTP mocking is RESPX route-level — never socket-level patching and never
  hand-rolled per test.
* Realistic config is loaded from external JSON fixtures
  (``tests/fixtures/config/*.json``) — no inline config literals.
* Integration tests run fully offline.

Frozen fixture names this harness exposes (qs-06 Code-Map / Tasks):

* ``mock_config_endpoint`` — RESPX route returning a 200 config JSON body for
  ``GET /config/{sdkKey}``.
* ``mock_tracking_endpoint`` — RESPX route capturing ``POST /track/{sdkKey}``
  tracking deliveries (returns 200; the route object records calls).
* ``sdk_with_mock_transport`` — an initialized :class:`~convert_sdk.core.Core`
  wired to deliver through a RESPX-mocked HTTPS base URL.
* ``in_memory_store`` — a fresh :class:`~convert_sdk.adapters.storage.in_memory.InMemoryDataStore`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
import respx

from convert_sdk import InMemoryDataStore
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.core import Core

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "config"

# A test-only HTTPS base URL. RESPX intercepts all requests to it; no real
# network access ever occurs (TLS-only NFR8 is still satisfied — the scheme is
# https).
MOCK_BASE_URL = "https://mock-cdn.convertexperiments.test"
SDK_KEY = "test-sdk-key-1234"


def load_config_fixture(name: str) -> Dict[str, Any]:
    """Load a realistic config fixture JSON by file name."""
    with (_FIXTURES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def minimal_config() -> Dict[str, Any]:
    return load_config_fixture("minimal_config.json")


@pytest.fixture
def full_config() -> Dict[str, Any]:
    return load_config_fixture("full_config.json")


@pytest.fixture
def in_memory_store() -> InMemoryDataStore:
    """A fresh per-test in-memory DataStore."""
    return InMemoryDataStore()


@pytest.fixture
def respx_mock():
    """A RESPX router scoped to ``MOCK_BASE_URL`` for the duration of a test."""
    with respx.mock(base_url=MOCK_BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def mock_config_endpoint(respx_mock, minimal_config):
    """Route ``GET /config/{sdkKey}`` to a 200 config JSON body.

    Returns the RESPX route so a test can assert on calls or override the body.
    """
    route = respx_mock.get(f"/config/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json=minimal_config)
    )
    return route


@pytest.fixture
def mock_tracking_endpoint(respx_mock):
    """Route ``POST /track/{sdkKey}`` to a 200; records each delivery.

    Returns the RESPX route; ``route.calls`` exposes the captured requests so
    tests can assert the POSTed batch shape.
    """
    route = respx_mock.post(f"/track/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    return route


@pytest.fixture
def sdk_with_mock_transport(respx_mock, mock_config_endpoint, mock_tracking_endpoint):
    """An initialized ``Core`` delivering through the RESPX-mocked HTTPS base URL.

    The Core is configured with ``sdk_key`` so it fetches config (via
    ``mock_config_endpoint``) and delivers tracking (via
    ``mock_tracking_endpoint``) over the mocked transport. A small ``batch_size``
    is NOT forced here — tests that want batch-size release set it explicitly.
    """
    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    config = SDKConfig(sdk_key=SDK_KEY, transport=TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(config, transport=transport).initialize()
    try:
        yield core
    finally:
        core.close()
