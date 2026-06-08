"""Integration: queue-lifecycle runtime matrix (qs-07).

Parametrized over the qs-07 #I-O-and-Edge-Case-Matrix runtime scenarios:

| Scenario        | Expected behavior                                          |
|-----------------|------------------------------------------------------------|
| explicit flush  | all queued events delivered before exit                    |
| timer-based     | periodic daemonic timer delivers without an explicit call  |
| atexit flush    | atexit callback attempts a best-effort final delivery      |
| no flush        | events silently dropped, process exits cleanly (no crash)  |
| SIGTERM pattern | a process-installed handler flushes before exit (opt-in)   |

In-process scenarios (explicit, timer) use the qs-06 RESPX harness. Process-exit
scenarios (atexit, no-flush, SIGTERM) are simulated with ``subprocess`` running a
tiny script with a stub transport that records deliveries to a file — never a
real gunicorn/Lambda (qs-07 #Boundaries-Constraints).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


from .conftest import SDK_KEY


# --- in-process scenarios (RESPX) -----------------------------------------


def test_explicit_flush_delivers_all_queued_events(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    core = sdk_with_mock_transport
    ctx = core.create_context("v1")
    ctx.track_conversion("purchase_completed")
    ctx.track_conversion("signup")
    core.flush()
    assert mock_tracking_endpoint.call_count == 1
    body = json.loads(mock_tracking_endpoint.calls[0].request.content)
    # Two goals for one visitor accumulate in a single visitors[] entry.
    events = body["visitors"][0]["events"]
    assert len(events) == 2


def test_timer_based_flush_delivers_without_explicit_call(
    respx_mock, mock_config_endpoint, mock_tracking_endpoint
):
    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core

    from .conftest import MOCK_BASE_URL

    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            auto_flush_interval_ms=50,
            transport=TransportConfig(base_url=MOCK_BASE_URL),
        ),
        transport=transport,
    ).initialize()
    try:
        core.create_context("v1").track_conversion("purchase_completed")
        # Wait for the daemonic timer to fire — no explicit flush() call.
        deadline = time.time() + 3.0
        while mock_tracking_endpoint.call_count < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert mock_tracking_endpoint.call_count >= 1
    finally:
        core.close()  # cancels the daemonic timer


# --- process-exit scenarios (subprocess simulation) -----------------------

# A self-contained script template: a stub transport writes each delivered batch
# as a JSON line to OUTFILE, so the parent can verify what was delivered after
# the child process exits. No real network, no gunicorn/Lambda.
_SCRIPT = textwrap.dedent(
    """
    import json, sys
    from convert_sdk.config import SDKConfig
    from convert_sdk.core import Core

    OUTFILE = sys.argv[1]
    SCENARIO = sys.argv[2]

    class RecordingTransport:
        def fetch_config(self, config):
            return {{
                "account_id": "100123",
                "project": {{"id": "200456", "key": "proj-key"}},
                "experiences": [], "features": [],
                "goals": [{{"id": "g1", "key": "purchase_completed"}}],
                "audiences": [], "segments": [],
            }}
        def send_tracking(self, payload, *, sdk_key):
            with open(OUTFILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload) + "\\n")
        def close(self):
            pass

    transport = RecordingTransport()
    core = Core(SDKConfig(sdk_key="k"), transport=transport).initialize()

    if SCENARIO == "atexit":
        from convert_sdk.tracking.flush import register_atexit_flush
        register_atexit_flush(core)
        core.create_context("v1").track_conversion("purchase_completed")
        # No explicit flush — rely on the best-effort atexit hook on clean exit.
    elif SCENARIO == "no_flush":
        core.create_context("v1").track_conversion("purchase_completed")
        # No flush, no atexit — events must be silently dropped, clean exit.
    elif SCENARIO == "sigterm":
        import signal, os
        def _handle(signum, frame):
            core.flush()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, _handle)
        core.create_context("v1").track_conversion("purchase_completed")
        os.kill(os.getpid(), signal.SIGTERM)

    sys.exit(0)
    """
)


def _run_scenario(tmp_path: Path, scenario: str) -> list:
    outfile = tmp_path / f"{scenario}.jsonl"
    script = tmp_path / f"{scenario}_run.py"
    # Write the generated script as UTF-8 explicitly: the template contains
    # non-ASCII characters (em-dashes in comments), and on Windows the default
    # encoding is cp1252, which would emit bytes the child interpreter cannot
    # parse as UTF-8 source (SyntaxError: Non-UTF-8 code ...).
    script.write_text(_SCRIPT.format(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(outfile), scenario],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # The child must exit cleanly (no crash) in every scenario.
    assert result.returncode == 0, result.stderr
    if not outfile.exists():
        return []
    return [
        json.loads(line)
        for line in outfile.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_atexit_scenario_attempts_final_delivery(tmp_path):
    delivered = _run_scenario(tmp_path, "atexit")
    # Best-effort atexit fired on clean interpreter shutdown -> one delivery.
    assert len(delivered) == 1
    assert delivered[0]["visitors"][0]["events"][0]["data"]["goalId"] == "g1"


def test_no_flush_scenario_drops_events_without_crash(tmp_path):
    delivered = _run_scenario(tmp_path, "no_flush")
    # Events silently dropped; the process still exited cleanly (asserted in
    # _run_scenario via returncode == 0).
    assert delivered == []


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "POSIX-only: Windows has no SIGTERM delivery to a Python handler — "
        "os.kill(pid, SIGTERM) maps to TerminateProcess and kills the process "
        "unconditionally, so the graceful-flush handler never runs. The "
        "Windows graceful-shutdown path is the atexit hook, covered by "
        "test_atexit_scenario_attempts_final_delivery."
    ),
)
def test_sigterm_scenario_flushes_before_exit(tmp_path):
    delivered = _run_scenario(tmp_path, "sigterm")
    # The process-installed SIGTERM handler flushed before exit.
    assert len(delivered) == 1


# --- payload parity gate (NFR21) ------------------------------------------


def test_delivered_payload_matches_story_2_2_serializer(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    # The flush body must be IDENTICAL to building the payload directly via the
    # Story 2.2 serializer (single serialization path, NFR21 parity).
    from convert_sdk.tracking.conversions import create_conversion
    from convert_sdk.tracking.payloads import build_tracking_payload

    core = sdk_with_mock_transport
    core.create_context("v1").track_conversion("purchase_completed", revenue=5.0)
    core.flush()

    delivered = json.loads(mock_tracking_endpoint.calls[0].request.content)

    snap = core.current_config
    event = create_conversion(
        snap, visitor_id="v1", goal_key="purchase_completed", revenue=5.0
    ).event
    expected = build_tracking_payload(snap, event, data_store=None)
    assert delivered == expected


# --- Story 2.4: per-trigger QUEUE_RELEASED reason (qs-07 matrix) -----------


def test_explicit_flush_emits_queue_released_reason_explicit(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    from convert_sdk.events import LifecycleEvent

    core = sdk_with_mock_transport
    seen = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda p, error=None: seen.append(p))
    core.create_context("v1").track_conversion("purchase_completed")
    core.flush()
    assert len(seen) == 1
    assert seen[0].reason.value == "explicit"


def test_batch_size_release_emits_queue_released_reason_size(
    respx_mock, mock_config_endpoint, mock_tracking_endpoint
):
    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core
    from convert_sdk.events import LifecycleEvent

    from .conftest import MOCK_BASE_URL

    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            batch_size=2,
            transport=TransportConfig(base_url=MOCK_BASE_URL),
        ),
        transport=transport,
    ).initialize()
    seen = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda p, error=None: seen.append(p))
    try:
        ctx = core.create_context("v1")
        ctx.track_conversion("purchase_completed")
        ctx.track_conversion("signup")  # reaches batch_size -> size release
        assert len(seen) == 1
        assert seen[0].reason.value == "size"
    finally:
        core.close()


def test_timer_release_emits_queue_released_reason_timeout(
    respx_mock, mock_config_endpoint, mock_tracking_endpoint
):
    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core
    from convert_sdk.events import LifecycleEvent

    from .conftest import MOCK_BASE_URL

    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            auto_flush_interval_ms=50,
            transport=TransportConfig(base_url=MOCK_BASE_URL),
        ),
        transport=transport,
    ).initialize()
    seen = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda p, error=None: seen.append(p))
    try:
        core.create_context("v1").track_conversion("purchase_completed")
        deadline = time.time() + 3.0
        while not seen and time.time() < deadline:
            time.sleep(0.02)
        assert seen, "timer-based release did not emit QUEUE_RELEASED"
        assert seen[0].reason.value == "timeout"
    finally:
        core.close()


def test_atexit_release_emits_queue_released_reason_atexit(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    import atexit as _atexit

    from convert_sdk.events import LifecycleEvent
    from convert_sdk.tracking.flush import register_atexit_flush

    core = sdk_with_mock_transport
    seen = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda p, error=None: seen.append(p))
    core.create_context("v1").track_conversion("purchase_completed")

    # A Flushable whose flush() drives the tracker's ATEXIT release path so the
    # best-effort atexit hook reports ReleaseReason.ATEXIT on its event (driven
    # in-process here so the emitted payload can be captured without relying on
    # interpreter shutdown).
    class _AtexitFlushable:
        def flush(self_inner):
            core._tracker.flush_atexit()  # type: ignore[attr-defined]

    cb = register_atexit_flush(_AtexitFlushable())
    try:
        cb()
        assert len(seen) == 1
        assert seen[0].reason.value == "atexit"
    finally:
        _atexit.unregister(cb)


def test_never_flushed_emits_nothing_and_does_not_crash(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    from convert_sdk.events import LifecycleEvent

    core = sdk_with_mock_transport
    seen = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda p, error=None: seen.append(p))
    # Track but never flush -> no release occurred -> no emission, no crash.
    core.create_context("v1").track_conversion("purchase_completed")
    assert seen == []
    assert mock_tracking_endpoint.call_count == 0
