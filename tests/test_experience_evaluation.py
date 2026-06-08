"""Story 1.4 — public local experience evaluation tests (SDK-4).

Covers the visitor-scoped ``Context`` and its public evaluation surface:

* ``Context.run_experience`` returns a typed result for a qualified visitor and
  ``None`` for normal misses (missing experience / unqualified visitor) — never
  raising (AC #1).
* Repeated evaluation of the same experience for the same visitor + snapshot is
  deterministic (AC #2).
* ``Context.run_experiences`` returns only applicable typed results and requires
  no network I/O on the evaluation path (AC #3).
* Request-time attribute overlays never mutate stored visitor state or the
  shared snapshot.
"""


from convert_sdk import Context, Core, SDKConfig
from convert_sdk.domain.results import ExperienceResult


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "audiences": [
        {
            "id": "a1",
            "key": "us-only",
            "rules": {
                "OR": [
                    {"AND": [{"OR_WHEN": [{"matching": {"match_type": "equals", "negated": False}, "key": "country", "value": "US"}]}]}
                ]
            },
        }
    ],
    "experiences": [
        {
            "id": "e1",
            "key": "unrestricted",
            "variations": [
                {"id": "v1", "key": "control", "traffic_allocation": 50.0},
                {"id": "v2", "key": "treatment", "traffic_allocation": 50.0},
            ],
        },
        {
            "id": "e2",
            "key": "us-experience",
            "audiences": ["a1"],
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        },
    ],
}


class _RecordingTransport:
    """Fake transport recording whether it was ever called."""

    def __init__(self):
        self.fetch_calls = 0

    def fetch_config(self, config):
        self.fetch_calls += 1
        return CONFIG

    def close(self):
        pass


def _ready_core(transport=None):
    return Core(SDKConfig(data=CONFIG), transport=transport).initialize()


def test_create_context_returns_context():
    core = _ready_core()
    ctx = core.create_context("visitor-1")
    assert isinstance(ctx, Context)


# --- AC #1: qualified typed result + non-exception no-result ------------------


def test_run_experience_returns_typed_result_for_qualified_visitor():
    ctx = _ready_core().create_context("visitor-1")
    result = ctx.run_experience("unrestricted")
    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "unrestricted"
    assert result.variation_id in {"v1", "v2"}


def test_run_experience_missing_experience_returns_none():
    ctx = _ready_core().create_context("visitor-1")
    assert ctx.run_experience("does-not-exist") is None


def test_run_experience_unqualified_visitor_returns_none():
    ctx = _ready_core().create_context("visitor-1", {"country": "CA"})
    assert ctx.run_experience("us-experience") is None


def test_run_experience_qualified_via_stored_attributes():
    ctx = _ready_core().create_context("visitor-1", {"country": "US"})
    result = ctx.run_experience("us-experience")
    assert result is not None
    assert result.variation_id == "v3"


# --- AC #2: determinism -------------------------------------------------------


def test_run_experience_is_deterministic():
    ctx = _ready_core().create_context("visitor-42")
    a = ctx.run_experience("unrestricted")
    b = ctx.run_experience("unrestricted")
    assert a is not None and b is not None
    assert a.variation_id == b.variation_id


# --- AC #3: run_experiences applicable-only + no network I/O ------------------


def test_run_experiences_returns_only_applicable_results():
    # CA visitor qualifies for the unrestricted experience but not the US one.
    ctx = _ready_core().create_context("visitor-1", {"country": "CA"})
    results = ctx.run_experiences()
    assert isinstance(results, list)
    keys = {r.experience_key for r in results}
    assert "unrestricted" in keys
    assert "us-experience" not in keys
    assert all(isinstance(r, ExperienceResult) for r in results)


def test_run_experiences_requires_no_network_io():
    transport = _RecordingTransport()
    core = Core(SDKConfig(data=CONFIG), transport=transport).initialize()
    calls_after_init = transport.fetch_calls
    ctx = core.create_context("visitor-7", {"country": "US"})
    ctx.run_experiences()
    ctx.run_experience("unrestricted")
    # No additional transport calls beyond initialization (direct config = 0).
    assert transport.fetch_calls == calls_after_init


# --- request-time overlay must not mutate stored state ------------------------


def test_request_time_overlay_does_not_mutate_stored_attributes():
    ctx = _ready_core().create_context("visitor-1", {"country": "CA"})
    # Request-time overlay qualifies the US experience for this call only.
    result = ctx.run_experience("us-experience", attributes={"country": "US"})
    assert result is not None
    # Stored attributes are unchanged: a subsequent call without overlay misses.
    assert ctx.run_experience("us-experience") is None


def test_stored_attributes_are_immutable_snapshot():
    source = {"country": "US"}
    ctx = _ready_core().create_context("visitor-1", source)
    source["country"] = "CA"  # mutate the caller's dict after construction
    # Context must have copied, so the US experience still qualifies.
    assert ctx.run_experience("us-experience") is not None


def test_visitor_id_is_exposed():
    ctx = _ready_core().create_context("visitor-99")
    assert ctx.visitor_id == "visitor-99"
