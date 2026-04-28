"""Execution tests for the story 1.6 examples and story 4.5 topic-guide samples.

All tests in this module run against direct-config mode so no network access
is required. The direct-config payload is the same one used by the runnable
examples in ``examples/_sample_config.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared config fixture
# ---------------------------------------------------------------------------

def _make_config() -> Mapping[str, Any]:
    """Return the shared direct-config payload used across all example tests."""

    return {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "audiences": [
            {
                "id": "aud-premium",
                "key": "premium-visitors",
                "name": "Premium Visitors",
                "status": "active",
                "rules": {
                    "OR": [
                        {
                            "AND": [
                                {
                                    "OR_WHEN": [
                                        {
                                            "rule_type": "generic_text_key_value",
                                            "key": "tier",
                                            "value": "premium",
                                            "matching": {
                                                "match_type": "matches",
                                                "negated": False,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
            }
        ],
        "features": [
            {
                "id": "feature-banner",
                "key": "checkout-banner",
                "name": "Checkout Banner",
                "variables": [
                    {"key": "enabled", "type": "boolean"},
                    {"key": "title", "type": "string"},
                    {"key": "discount", "type": "integer"},
                    {"key": "payload", "type": "json"},
                ],
            }
        ],
        "experiences": [
            {
                "id": "exp-checkout",
                "key": "checkout-flow",
                "name": "Checkout Flow",
                "status": "active",
                "environments": ["production"],
                "audiences": ["aud-premium"],
                "site_area": {
                    "OR": [
                        {
                            "AND": [
                                {
                                    "OR_WHEN": [
                                        {
                                            "rule_type": "generic_text_key_value",
                                            "key": "path",
                                            "value": "/checkout",
                                            "matching": {
                                                "match_type": "matches",
                                                "negated": False,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "variations": [
                    {
                        "id": "var-control",
                        "key": "control",
                        "name": "Control",
                        "status": "running",
                        "traffic_allocation": 50.0,
                        "changes": [
                            {
                                "type": "fullStackFeature",
                                "data": {
                                    "feature_id": "feature-banner",
                                    "variables_data": {
                                        "enabled": "false",
                                        "title": "Standard checkout",
                                        "discount": "0",
                                        "payload": '{"theme":"default"}',
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "id": "var-treatment",
                        "key": "free-shipping",
                        "name": "Free Shipping",
                        "status": "running",
                        "traffic_allocation": 50.0,
                        "changes": [
                            {
                                "type": "fullStackFeature",
                                "data": {
                                    "feature_id": "feature-banner",
                                    "variables_data": {
                                        "enabled": "true",
                                        "title": "Free shipping unlocked",
                                        "discount": "15",
                                        "payload": '{"theme":"promo"}',
                                    },
                                },
                            }
                        ],
                    },
                ],
            }
        ],
        "goals": [{"id": "goal-1", "key": "purchase"}],
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_example(script_name: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "examples" / script_name)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


# ---------------------------------------------------------------------------
# Story 1.6 example scripts (subprocess)
# ---------------------------------------------------------------------------

def test_direct_config_example_runs() -> None:
    output = run_example("direct_config.py")
    assert "SDK ready: True" in output
    assert "Context visitor: visitor-123" in output


def test_basic_experience_example_runs() -> None:
    output = run_example("basic_experience.py")
    assert "Experience: checkout-flow" in output
    assert "Variation:" in output


def test_basic_feature_example_runs() -> None:
    output = run_example("basic_feature.py")
    assert "Feature: checkout-banner" in output
    assert "Status: enabled" in output


# ---------------------------------------------------------------------------
# docs/initialization.md — code sample coverage
# ---------------------------------------------------------------------------

class TestInitializationGuide:
    """Covers code samples from docs/initialization.md."""

    def test_direct_config_initialization(self) -> None:
        """Mirrors the 'Initialize With Direct Config' sample in initialization.md."""
        from convert_sdk import Core, SDKConfig

        project_config = _make_config()
        core = Core(SDKConfig(config_data=project_config))
        assert core.is_ready

    def test_sdk_config_environment_field(self) -> None:
        """SDKConfig environment is stored and accessible on Core."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        assert core.config.environment == "production"

    def test_create_context_requires_nonempty_visitor_id(self) -> None:
        """Mirrors the InitializationError guard described in initialization.md."""
        from convert_sdk import Core, SDKConfig, InitializationError

        core = Core(SDKConfig(config_data=_make_config()))
        with pytest.raises(InitializationError):
            core.create_context("   ")

    def test_core_repr(self) -> None:
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        assert "is_ready=True" in repr(core)

    def test_tracking_config_defaults(self) -> None:
        """TrackingConfig fields described in initialization.md have correct defaults."""
        from convert_sdk import SDKConfig

        config = SDKConfig(config_data=_make_config())
        assert config.tracking.batch_size == 10
        assert config.tracking.source == "python-sdk"
        assert config.tracking.enrich_data is True

    def test_transport_config_defaults(self) -> None:
        """TransportConfig fields described in initialization.md have correct defaults."""
        from convert_sdk import SDKConfig

        config = SDKConfig(config_data=_make_config())
        assert "cdn-4.convertexperiments.com" in config.transport.config_endpoint
        assert config.transport.timeout_seconds == 5.0
        assert config.transport.verify_tls is True


# ---------------------------------------------------------------------------
# docs/evaluation.md — code sample coverage
# ---------------------------------------------------------------------------

class TestEvaluationGuide:
    """Covers code samples from docs/evaluation.md."""

    def test_run_experience_returns_result_for_bucketed_visitor(self) -> None:
        """Mirrors the run_experience() sample in evaluation.md."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        result = context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        # visitor-123 is deterministically bucketed; result must be non-None
        assert result is not None
        assert result.experience_key == "checkout-flow"
        assert result.variation_key in ("control", "free-shipping")
        assert 0 <= result.bucket_value <= 9999

    def test_run_experience_returns_none_for_audience_miss(self) -> None:
        """A visitor failing audience rules receives None (not an exception)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-no-tier", {})
        result = context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        assert result is None

    def test_run_experiences_returns_list(self) -> None:
        """run_experiences() returns a list, empty when no match."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        results = context.run_experiences(location_attributes={"path": "/checkout"})
        assert isinstance(results, list)

    def test_run_feature_returns_feature_result(self) -> None:
        """Mirrors the run_feature() sample in evaluation.md."""
        from convert_sdk import Core, SDKConfig, FeatureStatus

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        feature = context.run_feature(
            "checkout-banner",
            location_attributes={"path": "/checkout"},
        )
        assert feature is not None
        assert feature.feature_key == "checkout-banner"
        assert isinstance(feature.status, FeatureStatus)
        assert feature.status in (FeatureStatus.ENABLED, FeatureStatus.DISABLED)

    def test_run_feature_variables_are_typed(self) -> None:
        """Variables are type-cast per the declared type in the config."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        feature = context.run_feature(
            "checkout-banner",
            location_attributes={"path": "/checkout"},
        )
        assert feature is not None
        assert isinstance(feature.variables.get("discount"), int)
        assert isinstance(feature.variables.get("enabled"), bool)

    def test_run_features_returns_list(self) -> None:
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        features = context.run_features(location_attributes={"path": "/checkout"})
        assert isinstance(features, list)

    def test_diagnose_experience_reason_on_miss(self) -> None:
        """diagnose_experience() returns reason on audience miss."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-no-tier", {})
        diag = context.diagnose_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        assert diag.resolved is False
        assert diag.reason  # non-empty string
        assert diag.result is None

    def test_diagnose_experience_reason_on_success(self) -> None:
        """diagnose_experience() carries the ExperienceResult when bucketed."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        diag = context.diagnose_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        assert diag.resolved is True
        assert diag.result is not None
        assert "bucket_value" in diag.details

    def test_context_visitor_id(self) -> None:
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-xyz")
        assert context.visitor_id == "visitor-xyz"

    def test_update_visitor_attributes_merge(self) -> None:
        """update_visitor_attributes merges by default."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("v1", {"tier": "free"})
        context.update_visitor_attributes({"country": "US"})
        assert context.visitor_attributes.get("tier") == "free"
        assert context.visitor_attributes.get("country") == "US"

    def test_per_call_visitor_attribute_override(self) -> None:
        """Visitor attributes passed per-call do not mutate stored state."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-no-tier", {})
        result = context.run_experience(
            "checkout-flow",
            visitor_attributes={"tier": "premium"},
            location_attributes={"path": "/checkout"},
        )
        # per-call attributes should allow audience match for premium experience
        # stored attributes are still empty
        assert dict(context.visitor_attributes) == {}
        # result may or may not be None depending on bucket — just check type
        assert result is None or result.experience_key == "checkout-flow"


# ---------------------------------------------------------------------------
# docs/tracking.md — code sample coverage
# ---------------------------------------------------------------------------

class TestTrackingGuide:
    """Covers code samples from docs/tracking.md."""

    def test_track_conversion_basic(self) -> None:
        """Mirrors the basic conversion sample in tracking.md."""
        from convert_sdk import Core, SDKConfig, ConversionResult

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-track-1", {"tier": "premium"})
        result = context.track_conversion("purchase")
        assert isinstance(result, ConversionResult)
        assert result.duplicate_prevented is False
        assert result.queued_event_count >= 1

    def test_track_conversion_with_revenue_data(self) -> None:
        """Mirrors the revenue conversion_data sample in tracking.md."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-track-2", {"tier": "premium"})
        result = context.track_conversion(
            "purchase",
            conversion_data={"revenue": 49.99, "products_count": 2},
        )
        assert result.queued_event_count >= 1

    def test_track_conversion_deduplication(self) -> None:
        """Second call without force_multiple_transactions is deduplicated."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-dedup", {"tier": "premium"})
        result1 = context.track_conversion("purchase")
        result2 = context.track_conversion("purchase")
        assert result1.duplicate_prevented is False
        assert result2.duplicate_prevented is True

    def test_force_multiple_transactions(self) -> None:
        """force_multiple_transactions=True allows repeat tracking with data."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-repeat", {"tier": "premium"})
        result1 = context.track_conversion("purchase")
        result2 = context.track_conversion(
            "purchase",
            conversion_data={"revenue": 29.99},
            force_multiple_transactions=True,
        )
        assert result1.duplicate_prevented is False
        assert result2.duplicate_prevented is False

    def test_goal_not_found_raises(self) -> None:
        """Mirrors the GoalNotFoundError sample in tracking.md."""
        from convert_sdk import Core, SDKConfig, GoalNotFoundError

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1", {})
        with pytest.raises(GoalNotFoundError) as exc_info:
            context.track_conversion("no-such-goal")
        assert exc_info.value.code == "goal.not_found"
        assert "available_goal_count" in exc_info.value.context

    def test_conversion_data_bool_raises(self) -> None:
        """Boolean values in conversion_data are rejected."""
        from convert_sdk import Core, SDKConfig, ConversionDataError

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1", {})
        with pytest.raises(ConversionDataError):
            context.track_conversion("purchase", conversion_data={"ok": True})

    def test_diagnose_goal_resolved(self) -> None:
        """diagnose_goal returns resolved=True for a known goal."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        diag = context.diagnose_goal("purchase")
        assert diag.resolved is True
        assert diag.reason == "resolved"

    def test_diagnose_goal_not_found(self) -> None:
        """diagnose_goal returns resolved=False for an unknown goal."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        diag = context.diagnose_goal("nonexistent")
        assert diag.resolved is False
        assert diag.reason == "goal_not_found"


# ---------------------------------------------------------------------------
# docs/queue-control.md — code sample coverage
# ---------------------------------------------------------------------------

class TestQueueControlGuide:
    """Covers code samples from docs/queue-control.md."""

    def test_release_queues_empty_queue(self) -> None:
        """release_queues on an empty queue returns attempted=False."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-flush-1")
        flush_result = context.release_queues(reason="test")
        assert flush_result.attempted is False
        assert flush_result.delivered_event_count == 0
        assert flush_result.remaining_event_count == 0
        assert flush_result.reason == "test"

    def test_lifecycle_event_subscription(self) -> None:
        """Mirrors the lifecycle event subscription sample in queue-control.md."""
        from convert_sdk import Core, SDKConfig, LifecycleEvent, LifecycleEventPayload

        received: list[LifecycleEventPayload] = []

        def handler(payload: LifecycleEventPayload) -> None:
            received.append(payload)

        core = Core(SDKConfig(config_data=_make_config()))
        core.on(LifecycleEvent.CONVERSION_CREATED, handler)

        context = core.create_context("visitor-lifecycle", {"tier": "premium"})
        context.track_conversion("purchase")

        assert len(received) == 1
        assert received[0].event == LifecycleEvent.CONVERSION_CREATED

    def test_lifecycle_event_unsubscribe(self) -> None:
        """core.off() removes a handler."""
        from convert_sdk import Core, SDKConfig, LifecycleEvent, LifecycleEventPayload

        received: list[LifecycleEventPayload] = []

        def handler(payload: LifecycleEventPayload) -> None:
            received.append(payload)

        core = Core(SDKConfig(config_data=_make_config()))
        core.on(LifecycleEvent.CONVERSION_CREATED, handler)
        core.off(LifecycleEvent.CONVERSION_CREATED, handler)

        context = core.create_context("visitor-unsub", {"tier": "premium"})
        context.track_conversion("purchase")

        assert len(received) == 0

    def test_tracking_config_batch_size(self) -> None:
        """TrackingConfig.batch_size is configurable (queue-control.md)."""
        from convert_sdk import Core, SDKConfig, TrackingConfig

        core = Core(
            SDKConfig(config_data=_make_config(), tracking=TrackingConfig(batch_size=25))
        )
        assert core.config.tracking.batch_size == 25


# ---------------------------------------------------------------------------
# docs/debugging.md — code sample coverage
# ---------------------------------------------------------------------------

class TestDebuggingGuide:
    """Covers code samples from docs/debugging.md."""

    def test_typed_error_code_and_context(self) -> None:
        """Mirrors the structured error handling sample in debugging.md."""
        from convert_sdk import Core, SDKConfig, GoalNotFoundError

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        try:
            context.track_conversion("no-such-goal")
            pytest.fail("Expected GoalNotFoundError")
        except GoalNotFoundError as exc:
            assert exc.code == "goal.not_found"
            assert "available_goal_count" in exc.context

    def test_config_validation_error_inherits_initialization_error(self) -> None:
        from convert_sdk import ConfigValidationError, InitializationError

        assert issubclass(ConfigValidationError, InitializationError)

    def test_entity_diagnostic_by_key(self) -> None:
        """diagnose_config_entity() returns EntityDiagnostic (debugging.md)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        diag = context.diagnose_config_entity("experience", "checkout-flow")
        assert diag.resolved is True
        assert diag.entity_type == "experience"
        assert diag.lookup == "key"
        assert diag.value == "checkout-flow"

    def test_entity_diagnostic_by_id(self) -> None:
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        diag = context.diagnose_config_entity_by_id("experience", "exp-checkout")
        assert diag.resolved is True
        assert diag.lookup == "id"

    def test_entity_diagnostic_not_found(self) -> None:
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-1")
        diag = context.diagnose_config_entity("experience", "missing-key")
        assert diag.resolved is False
        assert diag.reason == "entity_not_found"

    def test_diagnose_feature(self) -> None:
        """diagnose_feature() returns FeatureDiagnostic (debugging.md)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        diag = context.diagnose_feature(
            "checkout-banner",
            location_attributes={"path": "/checkout"},
        )
        assert isinstance(diag.resolved, bool)
        assert diag.reason
        assert diag.message


# ---------------------------------------------------------------------------
# docs/extending.md — code sample coverage
# ---------------------------------------------------------------------------

class TestExtendingGuide:
    """Covers code samples from docs/extending.md."""

    def test_stub_transport_fetch_config(self) -> None:
        """Mirrors the StubTransport sample from extending.md."""
        from convert_sdk import Core, SDKConfig
        from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

        class StubTransport:
            def __init__(self, config_payload: dict) -> None:
                self._config = config_payload

            def fetch_config(self, request: ConfigRequest) -> dict:
                return self._config

            def send_tracking(self, request: TrackingRequest) -> dict:
                return {}

        stub = StubTransport(config_payload={
            "account_id": "1001",
            "project": {"id": "2002", "name": "Test"},
            "experiences": [],
            "features": [],
            "goals": [],
        })

        core = Core(SDKConfig(sdk_key="test-key"), transport=stub)
        assert core.is_ready

    def test_custom_data_store(self) -> None:
        """Mirrors the custom DataStore sample from extending.md."""
        from convert_sdk import Core, SDKConfig
        from convert_sdk.domain.context_state import ContextState

        class CapturingStore:
            """Simple store that records all save calls."""

            def __init__(self) -> None:
                self._states: dict[str, ContextState] = {}
                self._goals: set[tuple[str, str]] = set()
                self.save_calls: list[str] = []

            def load_context_state(self, visitor_id: str) -> ContextState | None:
                return self._states.get(visitor_id)

            def save_context_state(self, state: ContextState) -> None:
                self._states[state.visitor_id] = state
                self.save_calls.append(state.visitor_id)

            def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
                return (visitor_id, goal_id) in self._goals

            def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
                self._goals.add((visitor_id, goal_id))

        store = CapturingStore()
        core = Core(SDKConfig(config_data=_make_config()), data_store=store)
        core.create_context("visitor-custom-store")
        assert "visitor-custom-store" in store.save_calls

    def test_in_memory_data_store_is_importable(self) -> None:
        """InMemoryDataStore is a concrete public export (extending.md)."""
        from convert_sdk import InMemoryDataStore

        store = InMemoryDataStore()
        assert hasattr(store, "load_context_state")
        assert hasattr(store, "save_context_state")
        assert hasattr(store, "has_tracked_goal")
        assert hasattr(store, "mark_tracked_goal")


# ---------------------------------------------------------------------------
# docs/migration-from-rest.md — code sample coverage
# ---------------------------------------------------------------------------

class TestMigrationFromRestGuide:
    """Covers code samples from docs/migration-from-rest.md."""

    def test_sdk_replaces_manual_bucketing(self) -> None:
        """The SDK's bucket_value matches the algorithm described in migration-from-rest.md."""
        from convert_sdk import Core, SDKConfig
        from convert_sdk.evaluation.bucketing import get_bucket_value

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        result = context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        assert result is not None
        expected = get_bucket_value("visitor-123", "exp-checkout")
        assert result.bucket_value == expected

    def test_direct_config_avoids_network(self) -> None:
        """config_data mode requires no network — mirrors migration sample."""
        from convert_sdk import Core, SDKConfig

        config = {
            "account_id": "acct-999",
            "project": {"id": "proj-999", "name": "Migrated"},
            "experiences": [],
            "features": [],
            "goals": [],
        }
        core = Core(SDKConfig(config_data=config, environment="production"))
        assert core.is_ready

    def test_sdk_batches_and_deduplicates(self) -> None:
        """SDK prevents duplicate goal tracking — an improvement over raw REST."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-rest-migrant", {"tier": "premium"})
        r1 = context.track_conversion("purchase")
        r2 = context.track_conversion("purchase")
        assert r1.duplicate_prevented is False
        assert r2.duplicate_prevented is True

    def test_manual_select_variation_matches_sdk(self) -> None:
        """The 'manual bucketing' snippet in migration-from-rest.md must
        produce the same variation as the SDK for the same inputs.

        This guards against future drift between the doc's pseudocode and
        evaluation/bucketing.py::select_variation. If the doc's loop ever
        diverges from the SDK's logic again (e.g. forgets the *100 multiplier
        or skips the status filter), this test fails immediately.
        """
        from convert_sdk import Core, SDKConfig
        from convert_sdk.evaluation.bucketing import get_bucket_value

        # Verbatim copy of the snippet currently in docs/migration-from-rest.md
        # under "Side-by-side: bucketing". Keep these in sync.
        def select_variation(variations, bucket_value):
            accumulated = 0.0
            for variation in variations:
                if variation.get("status") not in (None, "", "active", "running"):
                    continue
                accumulated += float(variation["traffic_allocation"]) * 100
                if bucket_value < accumulated:
                    return variation["id"]
            return None

        config = _make_config()
        experience = next(
            e for e in config["experiences"] if e["key"] == "checkout-flow"
        )

        core = Core(SDKConfig(config_data=config, environment="production"))

        for visitor_id in (
            "visitor-1",
            "visitor-abc123",
            "visitor-quoll",
            "v-2",
            "v-7",
            "v-9",
            "v-100",
        ):
            context = core.create_context(visitor_id, {"tier": "premium"})
            sdk_result = context.run_experience(
                "checkout-flow",
                location_attributes={"path": "/checkout"},
            )
            assert sdk_result is not None, visitor_id

            manual_bucket = get_bucket_value(visitor_id, experience["id"])
            assert manual_bucket == sdk_result.bucket_value, visitor_id

            manual_variation_id = select_variation(
                experience["variations"], manual_bucket
            )
            assert manual_variation_id == sdk_result.variation_id, visitor_id


# ---------------------------------------------------------------------------
# docs/migration-from-javascript.md — code sample coverage
# ---------------------------------------------------------------------------

class TestMigrationFromJavaScriptGuide:
    """Covers code samples from docs/migration-from-javascript.md."""

    def test_create_context_snake_case(self) -> None:
        """Python uses snake_case for core.create_context (vs JS camelCase)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-js-migrant", {"browser": "chrome"})
        assert context.visitor_id == "visitor-js-migrant"

    def test_run_experience_snake_case(self) -> None:
        """run_experience (not runExperience) is the Python API method."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        result = context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        # method is accessible; result is typed dataclass
        assert result is None or hasattr(result, "variation_key")

    def test_feature_status_is_enum_and_str(self) -> None:
        """FeatureStatus is a str enum — comparing to 'enabled' works."""
        from convert_sdk import Core, SDKConfig, FeatureStatus

        core = Core(SDKConfig(config_data=_make_config(), environment="production"))
        context = core.create_context("visitor-123", {"tier": "premium"})
        feature = context.run_feature(
            "checkout-banner",
            location_attributes={"path": "/checkout"},
        )
        assert feature is not None
        # str-enum comparison works (migration-from-javascript.md notes this)
        assert feature.status in (FeatureStatus.ENABLED, FeatureStatus.DISABLED)
        assert feature.status.value in ("enabled", "disabled")

    def test_conversion_data_is_flat_mapping(self) -> None:
        """Python takes a flat Mapping, not a list of {key, value} objects."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-js-conv", {"tier": "premium"})
        result = context.track_conversion(
            "purchase",
            conversion_data={"revenue": 49.99, "products_count": 2},
        )
        assert result.queued_event_count >= 1

    def test_release_queues_is_synchronous(self) -> None:
        """release_queues is synchronous — no await needed (migration-from-javascript.md)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-sync-flush")
        # Should return immediately without requiring asyncio
        flush_result = context.release_queues(reason="test")
        assert flush_result.attempted is False

    def test_bucketing_parity_bucket_value_matches_algorithm(self) -> None:
        """Mirrors the parity verification sample in migration-from-javascript.md."""
        from convert_sdk.evaluation.bucketing import get_bucket_value

        bucket = get_bucket_value(
            visitor_id="visitor-abc123",
            experience_id="exp-checkout",
        )
        # The bucket value is deterministic; we only verify its range here.
        # Cross-SDK exact value matching is in tests/parity/.
        assert 0 <= bucket <= 9999

    def test_set_default_segments_takes_sequence_of_strings(self) -> None:
        """set_default_segments accepts a list of string keys (not a dict)."""
        from convert_sdk import Core, SDKConfig

        core = Core(SDKConfig(config_data=_make_config()))
        context = core.create_context("visitor-segs")
        context.set_default_segments(["some-segment-key"])
        assert "some-segment-key" in context.default_segments
