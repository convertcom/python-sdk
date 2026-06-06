"""Story 1.2 — Core initialization tests (SDK-3).

Covers ``Core`` initialization from either direct config data or an ``sdkKey``,
authoritative readiness state, and immutable snapshot access:

* Direct-config init does NOT invoke transport and stores an immutable snapshot
  (AC #1).
* sdkKey init fetches config through the transport path and stores the snapshot
  (AC #2).
* Malformed config and transport failures raise typed, diagnosable errors and
  the Core does not become ready (AC #3).
* A non-HTTPS transport raises a typed error before any I/O (AC #4 / NFR8).

Transport is exercised through a lightweight in-test fake implementing the
transport protocol, so these tests stay at the Core/orchestration layer and do
not depend on real HTTP. (Route-shape parity is asserted in
``test_httpx_transport.py``.)
"""

import pytest

from convert_sdk import Core, SDKConfig, TransportConfig
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.errors import ConfigLoadError, InvalidConfigError, TransportError


VALID_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [{"id": "e1", "key": "exp-one", "variations": []}],
    "features": [],
}


class _RecordingTransport:
    """Fake transport implementing the protocol; records whether it was called."""

    def __init__(self, *, response=None, error=None):
        self._response = response if response is not None else VALID_CONFIG
        self._error = error
        self.fetch_calls = 0
        self.closed = False

    def fetch_config(self, config):
        self.fetch_calls += 1
        if self._error is not None:
            raise self._error
        return self._response

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# --- Direct-config initialization (AC #1) ---------------------------------


def test_direct_config_init_does_not_invoke_transport():
    transport = _RecordingTransport()
    core = Core(SDKConfig(data=VALID_CONFIG), transport=transport)
    core.initialize()

    assert core.is_ready is True
    assert transport.fetch_calls == 0


def test_direct_config_stores_immutable_snapshot():
    core = Core(SDKConfig(data=VALID_CONFIG))
    core.initialize()

    snap = core.current_config
    assert isinstance(snap, ConfigSnapshot)
    assert snap.account_id == "100123"
    with pytest.raises(Exception):
        snap.account_id = "tampered"  # type: ignore[misc]


def test_not_ready_before_initialize():
    core = Core(SDKConfig(data=VALID_CONFIG))
    assert core.is_ready is False
    assert core.current_config is None


# --- sdkKey initialization (AC #2) ----------------------------------------


def test_sdk_key_init_fetches_through_transport():
    transport = _RecordingTransport(response=VALID_CONFIG)
    core = Core(SDKConfig(sdk_key="sdkkey123"), transport=transport)
    core.initialize()

    assert transport.fetch_calls == 1
    assert core.is_ready is True
    assert core.current_config.account_id == "100123"


# --- Failure paths (AC #3) ------------------------------------------------


def test_malformed_direct_config_raises_typed_error_and_stays_not_ready():
    core = Core(SDKConfig(data={"experiences": []}))  # missing account_id/project
    with pytest.raises(InvalidConfigError):
        core.initialize()
    assert core.is_ready is False
    assert core.current_config is None


def test_transport_failure_raises_config_load_error():
    transport = _RecordingTransport(
        error=ConfigLoadError("config fetch failed", endpoint="https://x/config/k", status_code=503)
    )
    core = Core(SDKConfig(sdk_key="sdkkey123"), transport=transport)
    with pytest.raises(ConfigLoadError):
        core.initialize()
    assert core.is_ready is False


def test_malformed_fetched_config_raises_typed_error():
    transport = _RecordingTransport(response={"experiences": []})  # invalid shape
    core = Core(SDKConfig(sdk_key="sdkkey123"), transport=transport)
    with pytest.raises(InvalidConfigError):
        core.initialize()
    assert core.is_ready is False


# --- TLS-only (AC #4 / NFR8) ----------------------------------------------


def test_non_https_transport_config_raises_before_any_io():
    """The typed error fires at TransportConfig construction — there is no path
    to reach Core.initialize() with an insecure transport."""
    with pytest.raises(TransportError):
        SDKConfig(sdk_key="k", transport=TransportConfig(base_url="http://nope"))


# --- Frozen Story 1.1 boundary --------------------------------------------


def test_core_importable_from_frozen_boundary():
    from convert_sdk import Context, Core, __version__  # noqa: F401

    assert Core is not None
