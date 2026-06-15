"""Offline guard test for the demo harness (F-066).

Asserts that LIVE mode constructs ``GET /api/v1/config/{sdkKey}`` against the
staging host ``cdn-4-staging.convertexperiments.com`` — deterministically
catching the PR #46 class of 404 (wrong config route / wrong host) without
requiring real network access.

All tests are fully offline (RESPX route-level mocking, never socket-level).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from convert_sdk import Core, SDKConfig, TransportConfig

# The shared staging project SDK key (public — account_id/project_id).
# Source: ../javascript-sdk/demo/nodejs/app.js:32; php-sdk .env.example
_STAGING_SDK_KEY = "10035569/10034190"
_STAGING_HOST = "https://cdn-4-staging.convertexperiments.com"

_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
_FIXTURE_PATH = _DEMO_DIR / "config_fixture.json"


def _load_fixture() -> dict:
    with _FIXTURE_PATH.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    raw.pop("_comment", None)
    return raw


# ---------------------------------------------------------------------------
# Guard test — LIVE mode builds the correct /api/v1/config/{sdkKey} route
# against the staging host (guards PR #46 class of 404)
# ---------------------------------------------------------------------------

class TestLiveModeConfigRoute:
    """Assert LIVE mode sends GET /api/v1/config/{sdkKey} to the staging host."""

    def test_live_mode_fetches_correct_route_against_staging_host(self):
        """LIVE mode must construct GET /api/v1/config/{sdkKey} on cdn-4-staging.

        This is the F-066 offline guard for the PR #46 class of bug: the SDK
        was building the wrong config route (missing /api/v1 prefix) and/or
        the wrong host, producing a 404. RESPX intercepts the request at
        route level so this assertion holds without any real network access.
        """
        fixture = _load_fixture()
        config_route = f"/api/v1/config/{_STAGING_SDK_KEY}"
        captured = {}

        with respx.mock(base_url=_STAGING_HOST, assert_all_called=False) as router:
            route = router.get(config_route).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            config = SDKConfig(
                sdk_key=_STAGING_SDK_KEY,
                environment="staging",
                transport=TransportConfig(base_url=_STAGING_HOST, timeout=10.0),
            )
            core = Core(config).initialize()
            try:
                assert core.is_ready
                captured["called"] = route.call_count
                captured["url"] = str(route.calls[0].request.url) if route.calls else None
            finally:
                core.close()

        assert captured["called"] == 1, (
            f"Expected exactly 1 call to {config_route!r}; got {captured['called']}. "
            "LIVE mode is not fetching the correct config route."
        )
        assert config_route in captured["url"], (
            f"Request URL {captured['url']!r} does not contain the expected route "
            f"{config_route!r} — SDK may be using the wrong route prefix."
        )
        assert "cdn-4-staging.convertexperiments.com" in captured["url"], (
            f"Request URL {captured['url']!r} does not target the staging host."
        )

    def test_live_mode_includes_environment_query_param(self):
        """LIVE mode with environment='staging' must append ?environment=staging."""
        fixture = _load_fixture()
        base_route = f"/api/v1/config/{_STAGING_SDK_KEY}"

        with respx.mock(base_url=_STAGING_HOST, assert_all_called=False) as router:
            route = router.get(base_route).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            config = SDKConfig(
                sdk_key=_STAGING_SDK_KEY,
                environment="staging",
                transport=TransportConfig(base_url=_STAGING_HOST),
            )
            core = Core(config).initialize()
            try:
                assert core.is_ready
                assert route.call_count == 1
                url = str(route.calls[0].request.url)
                assert "environment=staging" in url, (
                    f"Expected 'environment=staging' query param in URL; got: {url!r}"
                )
            finally:
                core.close()

    def test_live_mode_wrong_host_does_not_match(self):
        """Confirms the guard is specific: a wrong host triggers no route match.

        If the SDK were building the request against the production host instead
        of the staging host, RESPX would not match and would raise a
        ``ConnectError`` (no route matches). This test documents that behavior
        to make the guard's specificity explicit — a route miss means the SDK
        is targeting the wrong host.
        """
        with respx.mock(base_url=_STAGING_HOST, assert_all_called=False) as router:
            router.get(f"/api/v1/config/{_STAGING_SDK_KEY}").mock(
                return_value=httpx.Response(200, json=_load_fixture())
            )
            # Point the SDK at the *production* host — no route matches
            production_host = "https://cdn-4.convertexperiments.com"
            config = SDKConfig(
                sdk_key=_STAGING_SDK_KEY,
                environment="staging",
                transport=TransportConfig(base_url=production_host),
            )
            from convert_sdk import ConfigLoadError
            with pytest.raises((ConfigLoadError, Exception)):
                Core(config).initialize()


# ---------------------------------------------------------------------------
# OFFLINE fixture integrity
# ---------------------------------------------------------------------------

class TestOfflineFixture:
    """Assert the committed config_fixture.json is well-formed and deterministic."""

    def test_fixture_loads_and_sdk_initializes(self):
        """The OFFLINE fixture must produce a ready SDK with no network."""
        fixture = _load_fixture()
        core = Core(SDKConfig(data=fixture)).initialize()
        try:
            assert core.is_ready
        finally:
            core.close()

    def test_fixture_has_real_staging_entity_keys(self):
        """Fixture must carry the real staging keys, not invented placeholders."""
        fixture = _load_fixture()
        assert fixture["account_id"] == "10035569", (
            "account_id must be the shared staging account 10035569"
        )
        assert fixture["project"]["id"] == "10034190", (
            "project.id must be the shared staging project 10034190"
        )

        experience_keys = [e["key"] for e in fixture.get("experiences", [])]
        assert "test-experience-ab-fullstack-1" in experience_keys, (
            "Fixture must contain the real experience key 'test-experience-ab-fullstack-1'"
        )

        feature_keys = [f["key"] for f in fixture.get("features", [])]
        assert "test-experience-ab-fullstack-4" in feature_keys, (
            "Fixture must contain the real feature rollout key 'test-experience-ab-fullstack-4' "
            "(PHP authoritative source: php-sdk/demo/laravel/config/convert.php:7). "
            "Note: 'test-feature-rollout-1' was the stale JS-only key; PHP is canonical."
        )

        goal_keys = [g["key"] for g in fixture.get("goals", [])]
        assert "button-primary-click" in goal_keys, (
            "Fixture must contain the real goal key 'button-primary-click'"
        )

    def test_fixed_visitor_deterministically_buckets(self):
        """demo-visitor-001 must deterministically bucket into variation-treatment."""
        fixture = _load_fixture()
        core = Core(SDKConfig(data=fixture)).initialize()
        try:
            context = core.create_context("demo-visitor-001")
            result = context.run_experience("test-experience-ab-fullstack-1")
            assert result is not None, (
                "demo-visitor-001 must bucket into test-experience-ab-fullstack-1"
            )
            assert result.variation_key == "variation-treatment", (
                f"Expected variation-treatment; got {result.variation_key!r}. "
                "The bucketing is non-deterministic or the fixture changed."
            )
        finally:
            core.close()

    def test_fixed_visitor_resolves_feature_with_typed_variables(self):
        """demo-visitor-001 must resolve test-experience-ab-fullstack-4 with typed vars.

        The feature rollout key is 'test-experience-ab-fullstack-4' per the PHP demo
        (php-sdk/demo/laravel/config/convert.php:7). The old JS key 'test-feature-rollout-1'
        was stale and absent from the staging snapshot.
        """
        from convert_sdk.domain.results import FeatureStatus
        fixture = _load_fixture()
        core = Core(SDKConfig(data=fixture)).initialize()
        try:
            context = core.create_context("demo-visitor-001")
            feature = context.run_feature("test-experience-ab-fullstack-4")
            assert feature is not None, (
                "demo-visitor-001 must resolve test-experience-ab-fullstack-4"
            )
            assert feature.status is FeatureStatus.ENABLED
            vars_ = dict(feature.variables)
            assert vars_["enabled"] is True, "enabled must be cast to bool True"
            assert isinstance(vars_["headline"], str), "headline must be str"
            assert isinstance(vars_["max_items"], int), "max_items must be int"
        finally:
            core.close()

    def test_fixed_visitor_tracks_conversion_queued(self):
        """demo-visitor-001 must successfully queue a button-primary-click conversion."""
        from convert_sdk.domain.results import ConversionStatus
        fixture = _load_fixture()
        core = Core(SDKConfig(data=fixture)).initialize()
        try:
            context = core.create_context("demo-visitor-001")
            result = context.track_conversion("button-primary-click", revenue=29.99)
            assert result.status is ConversionStatus.QUEUED
            assert result.tracked is True
            assert result.goal_key == "button-primary-click"
        finally:
            core.close()
