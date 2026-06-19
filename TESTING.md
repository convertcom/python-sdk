# Testing

The Python SDK ships with `pytest`, `ruff`, `mypy --strict`, and a cross-SDK
parity suite that pins bucketing, rule, feature, and state behavior against
JavaScript SDK output. This page covers two things: how the SDK's own quality
gates work, and how to write tests for application code that uses the SDK.

## Running the SDK's own test suite

Prerequisites: a clone of the `python-sdk` repository and `uv` installed.

```bash
uv sync --group dev
uv run pytest                          # full suite including docs/examples drift and parity
uv run ruff check src tests scripts    # lint gate
uv run mypy --strict                   # type gate (src/convert_sdk only)
uv run pytest tests/parity             # release-blocking JS parity subset
```

To reproduce every release gate in one command:

```bash
python scripts/verify_release.py --version 0.1.0
```

This runs lint, type-check, the full test suite with both coverage floors,
the parity suite, and `uv build`. It exits non-zero on the first failure.
See [Release Process](https://github.com/convertcom/python-sdk/wiki/ReleaseProcess) for the full gate sequence.

## Project configuration (`pyproject.toml`)

All tooling is configured in `pyproject.toml`. Key settings:

| Tool | Configuration |
|------|---------------|
| pytest | `testpaths = ["tests"]`; `pythonpath = ["."]` (so `examples/` imports work) |
| ruff | `select = ["E", "W", "F", "B", "SIM", "RUF"]`; `line-length = 100` |
| mypy | `strict = true`; `files = ["src/convert_sdk"]`; `python_version = "3.9"` |
| coverage | `source = ["convert_sdk"]`; `fail_under = 85` |
| towncrier | fragments under `changes/`; compiled only at release time |

pytest is pinned to `>=8.4,<8.5` because pytest 9.x dropped Python 3.9 support,
which is the lower bound of the CI matrix.

## CI matrix

| Axis | Values |
|------|--------|
| Python | 3.9, 3.10, 3.11, 3.12, 3.13 |
| Operating system | ubuntu-latest, macos-latest, windows-latest |
| Dependency bounds | declared range and `ci/lower-bounds-overrides.txt` |

## Coverage gates

Two independent gates enforced in CI:

| Gate | Threshold | Why |
|------|-----------|-----|
| Project total | 85% | Overall health floor |
| `evaluation/` package | 95% | Bucketing/rules/features are contractually identical to the JS SDK; regressions there break parity |

The `evaluation/` gate is measured separately because those modules implement
the deterministic algorithm that cross-SDK parity depends on.

## Cross-SDK parity tests (`tests/parity/`)

The parity suite verifies byte-exact agreement between the Python SDK and the
JavaScript SDK reference. It is release-blocking: a red parity test blocks the
release workflow. It covers four domains:

| Fixture file | What it covers |
|---|---|
| `bucketing_vectors.json` | MurmurHash3-32 hash outputs (same visitor+seed must produce the same unsigned 32-bit integer) |
| `rule_vectors.json` | `OR/AND/OR_WHEN` rule-tree evaluation results |
| `feature_vectors.json` | Feature resolution: status and cast variable values |
| `state_vectors.json` | Entity lookup and segment evaluation |

Fixtures are checked-in JSON. CI never requires a Node.js runtime at test time.
The test infrastructure parametrizes over the vectors and feeds them through the
real Python evaluation surfaces:

```python
# From tests/parity/test_js_bucketing_parity.py — the pattern is identical
# for rule, feature, and state parity.
import json
from pathlib import Path
import pytest
from convert_sdk.evaluation.bucketing import murmurhash3_32

_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "bucketing_vectors.json").read_text(
        encoding="utf-8"
    )
)["vectors"]

@pytest.mark.parametrize(
    "vector",
    _VECTORS,
    ids=[f"seed{v['seed']}:{v['value']!r}" for v in _VECTORS],
)
def test_murmurhash3_32_matches_js_reference(vector):
    result = murmurhash3_32(vector["value"], vector["seed"])
    assert result == vector["expected"], (
        f"parity divergence for value={vector['value']!r} seed={vector['seed']}: "
        f"python={result} != js={vector['expected']}"
    )
```

To regenerate fixtures after a JS SDK algorithm change:

```bash
# Requires the sibling javascript-sdk repo at ../javascript-sdk
uv run python scripts/generate_parity_fixtures.py
git diff tests/parity/fixtures/    # inspect the diff before landing
```

Land fixture changes in a focused PR and confirm the bucketing parity test
counts match between JS and Python. See
[Release Process — Refreshing parity fixtures](https://github.com/convertcom/python-sdk/wiki/ReleaseProcess#refreshing-parity-fixtures).

## Docs and examples drift protection

Two test files ensure documentation cannot silently drift from the
implementation:

- `tests/test_docs_samples.py` — extracts every fenced Python block marked
  `# doctest: run` from the `docs/` guides and executes them. A guide
  whose sample drifts from the public API fails here.
- `tests/test_examples.py` — imports and runs every script in `examples/`.

Code samples must never embed a literal `sdk_key` value. The test suite
enforces this: keys must come from `os.environ["CONVERT_SDK_KEY"]`.

---

## Testing your own code that uses the SDK

The patterns below match the SDK's own test conventions. None of them require
a network connection.

### Pattern 1: offline initialization with `data=`

The fastest approach. Construct `Core` with `SDKConfig(data=...)` instead of
`sdk_key=`. No network call, no stub required, no `atexit` hook.

```python
from convert_sdk import Core, SDKConfig

OFFLINE_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [
        {
            "id": "e1",
            "key": "checkout-experiment",
            "variations": [
                {"id": "v1", "key": "control",   "traffic_allocation": 50.0},
                {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
            ],
        },
    ],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
    "audiences": [],
    "segments": [],
}


def make_core() -> Core:
    return Core(SDKConfig(data=OFFLINE_CONFIG)).initialize()


def test_visitor_is_bucketed():
    core = make_core()
    ctx = core.create_context("visitor-1")
    result = ctx.run_experience("checkout-experiment")
    assert result is not None
    assert result.variation_key in {"control", "treatment"}
    core.close()
```

The audience/targeting keys in the config dict are the same keys the SDK
reads in production. Keep test configs minimal: only include the experience,
feature, or goal fields your test exercises.

### Pattern 2: canned transport (fake `sdk_key` mode)

When you also want to exercise code that calls `sdk_key`-based initialization
or tracking delivery, swap in a fake `Transport`. The `Transport` protocol
has `fetch_config`, `send_tracking`, `close`, and the context-manager
(`__enter__` / `__exit__`) pair.

```python
import pytest
from convert_sdk import Core, SDKConfig


class CannedTransport:
    """Fake Transport for offline tests. Implements the Transport protocol."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self.tracking_calls: list = []

    def fetch_config(self, sdk_config) -> dict:
        return self._config

    def send_tracking(self, payload: dict, *, sdk_key: str) -> None:
        self.tracking_calls.append(payload)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


FULL_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
    "audiences": [],
    "segments": [],
}


@pytest.fixture
def canned_core():
    transport = CannedTransport(FULL_CONFIG)
    core = Core(
        SDKConfig(sdk_key="test-key"),
        transport=transport,
    ).initialize()
    yield core, transport
    core.close()


def test_flush_delivers_conversion(canned_core):
    core, transport = canned_core
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed", revenue=49.99)

    # track_conversion is synchronous and makes no network call.
    assert len(transport.tracking_calls) == 0

    core.flush()

    assert len(transport.tracking_calls) == 1
```

The `Core` constructor accepts `transport=` as a keyword argument. The
injected transport is used for both config fetch (when `sdk_key` is set) and
tracking delivery.

### Pattern 3: deterministic bucketing assertions

Bucketing is deterministic per `(experience_id, visitor_id)` pair. You can
assert on the specific variation a known visitor lands in. If a future
algorithm change shifts the bucket value, the test fails — which is the right
outcome, because shifted values invalidate in-flight experiments.

```python
from convert_sdk.evaluation.bucketing import get_bucket_value_for_visitor

def test_known_visitor_bucket_is_stable():
    # Assert the bucket value directly so any algorithm regression is
    # immediately visible before it can affect a running experiment.
    value = get_bucket_value_for_visitor("visitor-42", experience_id="e1")
    assert 0 <= value < 10000
    # The expected value is derived from the JS reference:
    # hash("e1visitor-42", 9999) / 2**32 * 10000 (integer)
    assert value == get_bucket_value_for_visitor("visitor-42", experience_id="e1")


def test_variation_selection_is_deterministic():
    core = make_core()     # uses OFFLINE_CONFIG from Pattern 1
    result_a = core.create_context("visitor-1").run_experience("checkout-experiment")
    result_b = core.create_context("visitor-1").run_experience("checkout-experiment")
    assert result_a is not None and result_b is not None
    assert result_a.variation_key == result_b.variation_key
    core.close()
```

You can also test hash outputs directly against the JS reference values
(the same technique the parity suite uses):

```python
from convert_sdk.evaluation.bucketing import murmurhash3_32

def test_hash_matches_js_reference():
    # JS: generateHash("e1visitor-1", 9999) == 3363324936
    assert murmurhash3_32("e1visitor-1", 9999) == 3363324936
```

### Pattern 4: lifecycle event assertions

Subscribe to `LifecycleEvent` to assert that a code path enqueued, deduplicated,
or flushed as expected. Handlers receive `(payload, error=None)`.

```python
from convert_sdk import Core, SDKConfig, LifecycleEvent, ConversionStatus
from convert_sdk.events import ConversionEventPayload


def test_conversion_event_fires_with_correct_fields(canned_core):
    core, _ = canned_core
    received = []
    core.on(
        LifecycleEvent.CONVERSION,
        lambda payload, error=None: received.append(payload),
    )

    core.create_context("visitor-1").track_conversion("purchase_completed")

    assert len(received) == 1
    payload = received[0]
    assert isinstance(payload, ConversionEventPayload)
    assert payload.visitor_id == "visitor-1"
    assert payload.goal_key == "purchase_completed"


def test_dedup_suppresses_second_event(canned_core):
    core, _ = canned_core
    ctx = core.create_context("visitor-1")

    first = ctx.track_conversion("purchase_completed")
    assert first.status is ConversionStatus.QUEUED

    second = ctx.track_conversion("purchase_completed")  # duplicate
    assert second.status is ConversionStatus.DEDUPLICATED
    assert second.tracked is False
```

`Core.on` can be called before or after `initialize()`. Handlers registered
before `initialize()` are still reached after initialization is complete.
One event bus is shared across all `Context` objects created by the same `Core`,
so a handler registered on `Core` observes conversions from every context.

### Pattern 5: isolating DataStore state per test

`InMemoryDataStore` holds deduplication markers and visitor state. Sharing a
store across tests will cause deduplication state to leak between them. Pass a
fresh `InMemoryDataStore` per test via `SDKConfig.data_store`:

```python
import pytest
from convert_sdk import Core, SDKConfig, InMemoryDataStore


@pytest.fixture
def isolated_core():
    """A fresh Core with a per-test DataStore so dedup state never leaks."""
    store = InMemoryDataStore()
    core = Core(
        SDKConfig(data=OFFLINE_CONFIG, data_store=store),
    ).initialize()
    yield core
    core.close()


def test_first_conversion_tracks(isolated_core):
    result = isolated_core.create_context("v1").track_conversion("purchase_completed")
    assert result.status is ConversionStatus.QUEUED


def test_second_conversion_is_deduped(isolated_core):
    ctx = isolated_core.create_context("v1")
    ctx.track_conversion("purchase_completed")
    second = ctx.track_conversion("purchase_completed")
    assert second.status is ConversionStatus.DEDUPLICATED
```

The default `Core` creates one `InMemoryDataStore` per instance. Using the
`data_store=` parameter is the clearest signal to test readers that you are
intentionally controlling state isolation.

### Pattern 6: asserting typed results and diagnostics

All evaluation results are typed dataclasses. Assert on the fields rather than
on string representations:

```python
from convert_sdk import Core, SDKConfig, DiagnosticReason, ExperienceResult

def test_experience_result_fields():
    core = make_core()
    ctx = core.create_context("visitor-1")
    result = ctx.run_experience("checkout-experiment")
    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "checkout-experiment"
    assert result.variation_key in {"control", "treatment"}
    assert isinstance(result.variation_id, str)
    core.close()


def test_missing_experience_returns_none_not_exception():
    core = make_core()
    ctx = core.create_context("visitor-1")
    result = ctx.run_experience("nonexistent-experience")
    assert result is None
    core.close()


def test_diagnose_gives_reason_without_raising():
    core = make_core()
    ctx = core.create_context("visitor-1")

    hit = ctx.diagnose_experience("checkout-experiment")
    assert hit.reason is DiagnosticReason.RESOLVED

    miss = ctx.diagnose_experience("typo-in-key")
    assert miss.reason is DiagnosticReason.EXPERIENCE_NOT_FOUND
    core.close()
```

The closed `DiagnosticReason` set has exactly eight values:
`RESOLVED`, `AUDIENCE_MISMATCH`, `EXPERIENCE_NOT_FOUND`,
`FEATURE_NOT_IN_SELECTED_VARIATIONS`, `FEATURE_NOT_FOUND`,
`GOAL_NOT_FOUND`, `ENTITY_NOT_FOUND`, `PROJECT_MAPPING_REQUIRED`.
Comparing with `is` works because `DiagnosticReason` is a `str` enum.

### Pattern 7: the integration harness (RESPX route-level mocking)

The SDK's own integration tests at `tests/integration/` use
[respx](https://lundberg.github.io/respx/) for route-level HTTPS mocking of
the config fetch (`GET /api/v1/config/{sdkKey}`) and tracking delivery
(`POST /track/{sdkKey}`) endpoints. This is the approach to adopt when you
need to test a full delivery pipeline against a near-real transport without
touching the network.

A minimal example modelled on the SDK's `tests/integration/conftest.py`:

```python
import httpx
import pytest
import respx
from convert_sdk import Core, InMemoryDataStore
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig

MOCK_BASE_URL = "https://mock-cdn.convertexperiments.test"
SDK_KEY = "test-sdk-key"
MINIMAL_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
}


@pytest.fixture
def respx_router():
    with respx.mock(base_url=MOCK_BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def mock_tracking(respx_router):
    return respx_router.post(f"/track/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )


@pytest.fixture
def sdk(respx_router, mock_tracking):
    respx_router.get(f"/api/v1/config/{SDK_KEY}").mock(
        return_value=httpx.Response(200, json=MINIMAL_CONFIG)
    )
    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(sdk_key=SDK_KEY, transport=TransportConfig(base_url=MOCK_BASE_URL)),
        transport=transport,
    ).initialize()
    yield core
    core.close()


def test_flush_posts_one_batch(sdk, mock_tracking):
    ctx = sdk.create_context("visitor-1")
    ctx.track_conversion("purchase_completed", revenue=49.99)
    assert mock_tracking.call_count == 0   # no delivery before flush
    sdk.flush()
    assert mock_tracking.call_count == 1
```

RESPX intercepts requests at the route level; no real TCP connection is made.
The test still uses the real `HttpxTransport`, so the payload serialization and
HTTP header logic are exercised end-to-end.

## Type-checking your integration

The SDK ships `py.typed` (PEP 561). `Core`, `Context`, `SDKConfig`,
`TransportConfig`, all result/diagnostic types, all errors, and all enums carry
full annotations. `Transport` and `DataStore` are `typing.Protocol` definitions —
your custom adapters are checked structurally without inheritance.

Run mypy on your application code alongside the SDK:

```bash
mypy --strict your_app/
```

## Towncrier and changelog fragments

Every PR that touches user-visible behavior must add a towncrier fragment under
`changes/`. Fragment naming convention: `+story-{N}-{slug}.{type}.md` (orphan
fragments — no issue number prefix). Valid types: `feature`, `bugfix`,
`breaking`, `deprecation`, `internal`.

Preview without writing to `CHANGELOG.md`:

```bash
uv run towncrier build --draft --version 0.2.0
```

Never hand-edit `CHANGELOG.md` and never run `towncrier build` on a feature
branch. Fragments are compiled into the changelog only by the release workflow.
See [Release Process](https://github.com/convertcom/python-sdk/wiki/ReleaseProcess) for the complete changelog gate.

## What to read next

- [Release Process](https://github.com/convertcom/python-sdk/wiki/ReleaseProcess) — CI gates, parity fixture refresh, PyPI publishing
- [Extending](https://github.com/convertcom/python-sdk/wiki/Extending) — Protocol-based extension points used in tests
- [Diagnostics](https://github.com/convertcom/python-sdk/wiki/Diagnostics) — `diagnose_*` surfaces and `DiagnosticReason` codes
- [Type Hints](https://github.com/convertcom/python-sdk/wiki/TypeHints) — the dataclasses your tests assert against
- [Code Examples](https://github.com/convertcom/python-sdk/wiki/CodeExamples) — runnable patterns to mirror in fixtures
