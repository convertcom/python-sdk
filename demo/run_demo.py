#!/usr/bin/env python3
"""Convert Python SDK — dual-mode manual-verification demo harness (F-066).

Two modes, OFFLINE as the default:

OFFLINE (default, zero credentials)
    Builds via direct config from the committed ``demo/config_fixture.json``
    using the REAL staging entity keys (not invented placeholders). Zero
    network access; deterministic output for a fixed visitor.

        python demo/run_demo.py

LIVE (opt-in, only when CONVERT_SDK_KEY is set)
    Builds via ``sdk_key`` against the shared staging project (10035569/10034190),
    pointing ``TransportConfig.base_url`` at the staging CDN host so the SDK
    fetches ``GET /api/v1/config/{sdkKey}`` over HTTPS. Set ``CONVERT_SDK_KEY``
    (and optionally ``CONVERT_AUTH_SECRET``) in the environment or in
    ``demo/.env`` (gitignored; never committed).

        CONVERT_SDK_KEY=10035569/10034190 python demo/run_demo.py

For each visitor the demo runs the full FullStack arc and prints what the SDK
decided:
    experience variation -> feature rollout (as experience) + variables
    -> segments -> conversion (goal + revenue)
    -> [LIVE] flush + delivery report

Patterns reused from ``scripts/verify_staging_transaction.py``:
- LIVE delivery report via ``core.on(LifecycleEvent.API_QUEUE_RELEASED, cb)``
- ``(visitor, goal)`` dedup behaviour documented in the output
- ``run_experiences()`` for attribution context before conversion

Audience attributes:
    The live staging audience ``10033684`` requires EITHER
    ``{"desktop": True, "browser": <anything-except-"CH">}`` OR
    ``{"mobile": True}``.  The demo defaults to ``{"mobile": True}`` (minimal
    single-attribute match) and honours an override via the env var
    ``CONVERT_DEMO_ATTRIBUTES`` (JSON string, e.g.
    ``CONVERT_DEMO_ATTRIBUTES='{"desktop": true}' python demo/run_demo.py``).
    These attributes are applied via ``context.set_attributes(...)`` before
    evaluation and are ALSO passed as the per-call ``attributes=`` overlay so
    the ``diagnose_experience`` call uses the same attributes.

Experiment-preview links (qs-02), opt-in via ``CONVERT_DEMO_PREVIEW``:
    Set ``CONVERT_DEMO_PREVIEW="{experienceId}.{variationId}"`` (dot-separated
    NUMERIC ids -- the canonical ``convert_preview=`` link value) to force one
    variation on the context, bypassing every normal qualification/bucketing
    gate for THAT experience only. In OFFLINE mode the fixture ships a
    dedicated draft/paused preview-only experience (numeric id
    ``900210001``, variations ``900210101``/``900210102``) that normal
    bucketing can NEVER serve -- only ``set_preview()`` renders it:

        CONVERT_DEMO_PREVIEW=900210001.900210101 python demo/run_demo.py

    A malformed value (non-numeric ids, extra dots, etc.) takes the AC7
    inert-with-warning path -- logged, never raised -- and the rest of the
    demo runs unaffected. See ``demo/README.md`` ("Testing preview links") for
    the full walkthrough including the zero-trace and LIVE-mode notes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Inline .env loader (stdlib only — no third-party dependency for the demo)
# ---------------------------------------------------------------------------
_DEMO_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Parse a simple KEY=value .env file and inject into os.environ.

    Rules:
    - Lines starting with '#' (after stripping) are comments; skip them.
    - Lines without '=' are skipped.
    - Values may be quoted with single or double quotes; quotes are stripped.
    - Only missing keys are set (never override an already-set variable).
    """
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            key = key.strip()
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


# Load demo/.env BEFORE reading any env vars
_load_dotenv(_DEMO_DIR / ".env")

# ---------------------------------------------------------------------------
# SDK imports (public API only)
# ---------------------------------------------------------------------------
from convert_sdk import (  # noqa: E402
    ConfigLoadError,
    ConversionStatus,
    Core,
    InvalidConfigError,
    LifecycleEvent,
    SDKConfig,
    TransportConfig,
    TransportError,
    parse_preview_param,
)

# ---------------------------------------------------------------------------
# Demo constants (real staging keys per F-066 ground truth)
# ---------------------------------------------------------------------------
# Shared staging SDK key (PUBLIC — account_id/project_id).
# Source: ../javascript-sdk/demo/nodejs/app.js:32 (sdkKey: '10035569/10034190')
#         ../php-sdk/demo/laravel/config/convert.php + .env.example
_SHARED_STAGING_SDK_KEY = "10035569/10034190"

# Experience key — JS: ../javascript-sdk/demo/nodejs/routes/events.js (experienceKey)
EXPERIENCE_KEY = "test-experience-ab-fullstack-1"

# Feature rollout key — JS: ../javascript-sdk/demo/nodejs/routes/events.js (featureRolloutKey)
# The spec designates 'test-feature-rollout-1' as the feature key (JS is authoritative).
# The Python demo calls run_feature(FEATURE_ROLLOUT_KEY) — resolving a declared feature
# with typed variable casting (bool/string/integer). The feature is linked to experience
# test-experience-ab-fullstack-1 via the variation's changes[].data.feature_id.
# LIVE staging may carry a different key; override via CONVERT_DEMO_FEATURE_ROLLOUT_KEY.
FEATURE_ROLLOUT_KEY = os.environ.get(
    "CONVERT_DEMO_FEATURE_ROLLOUT_KEY", "test-feature-rollout-1"
)

# Segment key — JS: ../javascript-sdk/demo/nodejs/routes/events.js (segmentsKey)
SEGMENT_KEY = "test-segment-1"

# Goal key — PHP: ../php-sdk/demo/laravel/config/convert.php (goal_key)
# (JS demo fires no conversion; PHP is the canonical source for this key)
GOAL_KEY = "button-primary-click"

# Location property required by the live staging location rules.
# Source: ../javascript-sdk/demo/nodejs/routes/events.js line 15-17
#         (locationProperties: { location: "events" })
# PHP: ../php-sdk/demo/laravel/app/Http/Controllers/EventsController.php:25,31
#      (locationProperties: ['location' => 'events'])
# The OFFLINE fixture is ungated so extra location attributes are ignored.
# Override via CONVERT_DEMO_LOCATION env var to retry other site areas if
# diagnose_experience reports a location-driven miss in LIVE mode.
_LOCATION_ATTRS: Dict[str, Any] = {
    "location": os.environ.get("CONVERT_DEMO_LOCATION", "events")
}

# Staging CDN host (pure host, no path). The SDK appends /api/v1/config/{sdkKey}.
# Source: scripts/verify_staging_transaction.py DEFAULT_HOST; config.py comment
STAGING_HOST = "https://cdn-4-staging.convertexperiments.com"

# Fixed OFFLINE visitor — deterministic bucketing, no random state
OFFLINE_VISITOR_ID = "demo-visitor-001"

# Default audience attributes satisfying the live staging audience 10033684.
# Audience rule: OR[ AND[desktop==true, browser != "CH"] , AND[mobile==true] ]
# Using {"mobile": True} — minimal single-attribute match, no browser dependency.
# Override via CONVERT_DEMO_ATTRIBUTES env var (JSON string).
_DEFAULT_AUDIENCE_ATTRS: Dict[str, Any] = {"mobile": True}

# ---------------------------------------------------------------------------
# Experiment-preview link demonstration (qs-02)
# ---------------------------------------------------------------------------
# The OFFLINE fixture (demo/config_fixture.json) carries a SECOND, standalone
# experience built ONLY to demonstrate preview links: 'preview-only-draft-
# experience' (numeric id 900210001), whose two variations BOTH carry
# status='paused' (non-running) — normal run_experience()/run_experiences()
# NEVER serve this experience, regardless of visitor/attributes/bucketing.
# Only Context.set_preview() bypasses that status gate. Its ids are numeric
# (unlike the string placeholder ids on the primary demo experience) because
# parse_preview_param() requires numeric-only dot-separated segments — the
# same shape a real Convert preview link (`?convert_preview=...`) carries.
#
# CONVERT_DEMO_PREVIEW_EXPERIENCE_KEY overrides the KEY the demo calls
# run_experience() with after set_preview() — needed for LIVE mode, where the
# targeted experience is a real staging draft/paused experience whose key the
# demo cannot infer from its numeric ids alone.
PREVIEW_EXPERIENCE_KEY = os.environ.get(
    "CONVERT_DEMO_PREVIEW_EXPERIENCE_KEY", "preview-only-draft-experience"
)
_PREVIEW_OFFLINE_EXPERIENCE_ID = "900210001"
_PREVIEW_OFFLINE_VARIATION_CONTROL_ID = "900210101"
_PREVIEW_OFFLINE_VARIATION_TREATMENT_ID = "900210102"
_PREVIEW_EXAMPLE_LINK = (
    f"{_PREVIEW_OFFLINE_EXPERIENCE_ID}.{_PREVIEW_OFFLINE_VARIATION_CONTROL_ID}"
)


def _resolve_audience_attrs() -> Dict[str, Any]:
    """Return audience attributes from CONVERT_DEMO_ATTRIBUTES env var or default."""
    raw = os.environ.get("CONVERT_DEMO_ATTRIBUTES", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            print(
                f"[WARN] CONVERT_DEMO_ATTRIBUTES is not valid JSON ({raw!r}); "
                "using default {mobile: true}",
                file=sys.stderr,
            )
    return dict(_DEFAULT_AUDIENCE_ATTRS)


# ---------------------------------------------------------------------------
# OFFLINE mode — direct config from the committed fixture
# ---------------------------------------------------------------------------

def _load_offline_config() -> Dict[str, Any]:
    fixture_path = _DEMO_DIR / "config_fixture.json"
    with fixture_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    # Strip the _comment field if present (not a valid SDK config field)
    raw.pop("_comment", None)
    return raw  # type: ignore[return-value]


def run_offline() -> int:
    """OFFLINE mode: zero credentials, deterministic, no network."""
    print("=" * 60)
    print("Convert Python SDK — OFFLINE demo")
    print("=" * 60)
    print("  config:   demo/config_fixture.json (committed fixture)")
    print(f"  visitor:  {OFFLINE_VISITOR_ID!r} (fixed, deterministic)")
    print()

    config_data = _load_offline_config()
    core = Core(SDKConfig(data=config_data)).initialize()
    assert core.is_ready, "SDK should be ready after direct-config initialize()"
    print("[SDK] Ready (direct config, no network)")
    print()

    audience_attrs = _resolve_audience_attrs()
    context = core.create_context(OFFLINE_VISITOR_ID)

    _run_visitor_arc(context, core, is_live=False, audience_attrs=audience_attrs)
    print()
    _run_preview_demo(context, is_live=False)

    core.close()
    return 0


# ---------------------------------------------------------------------------
# LIVE mode — sdk_key against the staging CDN host
# ---------------------------------------------------------------------------

def run_live(sdk_key: str, auth_secret: Optional[str]) -> int:
    """LIVE mode: fetches real config from staging, delivers a real conversion."""
    visitor_id = os.environ.get("CONVERT_DEMO_VISITOR_ID", "demo-visitor-001")
    host = os.environ.get("CONVERT_DEMO_HOST", STAGING_HOST)

    print("=" * 60)
    print("Convert Python SDK — LIVE demo (staging)")
    print("=" * 60)
    print(f"  sdk_key:  {sdk_key!r}")
    print(f"  host:     {host}")
    print(f"  visitor:  {visitor_id!r}")
    print(f"  auth:     {'yes (CONVERT_AUTH_SECRET set)' if auth_secret else 'no (public key)'}")
    print()

    # Delivery report captured via the lifecycle event
    delivery: Dict[str, Any] = {}

    def on_queue_released(payload: Any, error: Optional[BaseException] = None) -> None:
        delivery["reason"] = getattr(payload, "reason", None)
        delivery["event_count"] = getattr(payload, "event_count", None)
        delivery["batch_size"] = getattr(payload, "batch_size", None)
        delivery["status_code"] = getattr(payload, "status_code", None)
        delivery["error"] = repr(error) if error is not None else None

    config = SDKConfig(
        sdk_key=sdk_key,
        environment="staging",
        transport=TransportConfig(
            base_url=host,
            timeout=float(os.environ.get("CONVERT_DEMO_TIMEOUT", "10")),
            auth_secret=auth_secret,
        ),
    )

    core = Core(config)
    core.on(LifecycleEvent.API_QUEUE_RELEASED, on_queue_released)

    print(f"[SDK] Fetching config from {host}/api/v1/config/{sdk_key} ...")
    try:
        core.initialize()
    except ConfigLoadError as exc:
        print(f"[SDK] Config fetch failed: {exc}", file=sys.stderr)
        print(
            "\nIf this is a 404, the SDK is building the wrong config route.",
            file=sys.stderr,
        )
        return 1
    except (InvalidConfigError, TransportError) as exc:
        print(f"[SDK] Init error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not core.is_ready:
        print("[SDK] Not ready after initialize(). Aborting.", file=sys.stderr)
        return 1

    print("[SDK] Ready (live config fetched from staging)")
    print()

    audience_attrs = _resolve_audience_attrs()
    context = core.create_context(visitor_id)

    _run_visitor_arc(context, core, is_live=True, audience_attrs=audience_attrs)
    print()
    _run_preview_demo(context, is_live=True)

    # Flush and report.  Tracking is delivered to the SEPARATE metrics endpoint
    # (not the config CDN): track_base_url / track / {sdkKey}, where the
    # [project_id] placeholder in track_base_url is substituted at request time.
    _track_template = config.transport.track_base_url
    print(
        f"[SDK] Flushing queue (delivering to metrics endpoint: "
        f"{_track_template}/track/{{sdkKey}}) ..."
    )
    core.flush()
    core.close()

    print()
    print("--- delivery report ---")
    print(f"  release reason:  {delivery.get('reason')}")
    print(
        f"  events delivered:{delivery.get('event_count')}"
        f" (batch_size={delivery.get('batch_size')})"
    )
    print(f"  HTTP status:     {delivery.get('status_code')}")
    if delivery.get("error"):
        print(f"  transport error: {delivery['error']}")

    status_code = delivery.get("status_code")
    if delivery.get("reason") is None:
        print("\nNo queue release occurred (nothing delivered — possibly deduplicated).")
        print("Run with CONVERT_DEMO_FORCE_MULTIPLE=1 to override dedup.")
        return 0

    delivered_ok = isinstance(status_code, int) and 200 <= status_code < 300
    if delivered_ok:
        print("\n[OK] Conversion delivered to staging.")
        print(f"  Visitor {visitor_id!r} converted goal {GOAL_KEY!r}")
        print("  Check the staging dashboard (Live Log / Conversions) for this visitor + goal.")
    else:
        print(f"\n[WARN] Tracking endpoint returned non-2xx ({status_code!r}).")
        print("  The conversion may not be recorded.")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Shared per-visitor arc (both modes)
# ---------------------------------------------------------------------------

def _run_visitor_arc(
    context: Any,
    core: Any,
    *,
    is_live: bool,
    audience_attrs: Dict[str, Any],
) -> None:
    """Run the full FullStack arc for one visitor and print the SDK decisions.

    ``audience_attrs`` is applied persistently via ``set_attributes`` AND passed
    as the per-call ``attributes=`` overlay so both the evaluation and the
    self-diagnosis calls use identical audience state.
    """
    if is_live:
        # Set default segments and audience attributes for LIVE staging only.
        # Staging audience 10033684: OR[ AND[desktop==true, browser!="CH"] , AND[mobile==true] ]
        # Not needed for OFFLINE (fixture is ungated; no audience rules).
        _default_segs: Dict[str, Any] = {"country": "US"}
        context.set_segments(_default_segs)
        print(f"[0a] set_segments({_default_segs!r})  (default segments — LIVE staging)")
        context.set_attributes(audience_attrs)
        print(f"[0b] set_attributes({audience_attrs!r})  (audience attrs for staging gating)")
        print()

    # --- Step 1: evaluate experience ---
    print(f"[1] run_experience({EXPERIENCE_KEY!r})")
    exp_result = context.run_experience(
        EXPERIENCE_KEY,
        attributes=audience_attrs if is_live else {},
        location_attributes=_LOCATION_ATTRS if is_live else {},
    )
    if exp_result is not None:
        print(f"    experience_key : {exp_result.experience_key}")
        print(f"    variation_key  : {exp_result.variation_key}")
        print(f"    variation_id   : {exp_result.variation_id}")
    else:
        print("    result         : None (visitor not bucketed)")
        diag = context.diagnose_experience(
            EXPERIENCE_KEY,
            attributes=audience_attrs,
            location_attributes=_LOCATION_ATTRS,
        )
        print(f"    diagnose       : reason={diag.reason.value!r}")
        print(f"    message        : {diag.message!r}")
        if diag.details:
            print(f"    details        : {dict(diag.details)!r}")
        print(
            "    HINT: EXPERIENCE_NOT_FOUND means the live config has no such key.\n"
            "          AUDIENCE_MISMATCH means audience/location rules did not match;\n"
            "          set CONVERT_DEMO_ATTRIBUTES env var to override attributes."
        )
    print()

    # --- Step 2: resolve the feature (typed variables via run_feature) ---
    # Source: ../javascript-sdk/demo/nodejs/routes/events.js (featureRolloutKey)
    # The spec designates run_feature as the correct call — it resolves the declared
    # feature definition and type-casts each variable (bool/string/integer).
    print(f"[2] run_feature({FEATURE_ROLLOUT_KEY!r})")
    from convert_sdk import FeatureResult  # noqa: F401 — used for type clarity
    feature_result = context.run_feature(
        FEATURE_ROLLOUT_KEY,
        attributes=audience_attrs if is_live else {},
        location_attributes=_LOCATION_ATTRS if is_live else {},
    )
    if feature_result is not None:
        print(f"    feature_key    : {feature_result.feature_key}")
        print(f"    status         : {feature_result.status.value}")
        print("    variables:")
        for var_name, var_value in feature_result.variables.items():
            print(f"      {var_name}: {var_value!r}  (type={type(var_value).__name__})")
        print(f"    via experience : {feature_result.experience_key}")
        print(f"    via variation  : {feature_result.variation_key}")
    else:
        print(f"    result         : None (feature {FEATURE_ROLLOUT_KEY!r} not resolved)")
        from convert_sdk import FeatureDiagnostic  # noqa: F401
        feat_diag = context.diagnose_feature(
            FEATURE_ROLLOUT_KEY,
            attributes=audience_attrs if is_live else {},
            location_attributes=_LOCATION_ATTRS if is_live else {},
        )
        print(f"    diagnose       : reason={feat_diag.reason.value!r}")
        print(f"    message        : {feat_diag.message!r}")
        if feat_diag.details:
            print(f"    details        : {dict(feat_diag.details)!r}")
        print(
            "    NOTE: FEATURE_NOT_FOUND means the loaded config has no feature\n"
            "          with this key. Try CONVERT_DEMO_FEATURE_ROLLOUT_KEY to override."
        )
    print()

    # --- Step 3: attach custom segments ---
    print(f"[3] set_segments({{{SEGMENT_KEY!r}: True}})")
    context.set_segments({SEGMENT_KEY: True})
    print(f"    default_segments: {dict(context.default_segments)}")
    print()

    # --- Step 4: track conversion ---
    force_multiple = os.environ.get("CONVERT_DEMO_FORCE_MULTIPLE", "") == "1"
    revenue = float(os.environ.get("CONVERT_DEMO_REVENUE", "29.99"))
    conv_data: Dict[str, Any] = {"source": "python-sdk-demo"}

    print(f"[4] track_conversion({GOAL_KEY!r}, revenue={revenue}, force_multiple={force_multiple})")
    conv_result = context.track_conversion(
        GOAL_KEY,
        revenue=revenue,
        conversion_data=conv_data,
        force_multiple=force_multiple,
    )
    print(f"    status   : {conv_result.status.value}")
    print(f"    tracked  : {conv_result.tracked}")
    print(f"    goal_key : {conv_result.goal_key}")
    print(f"    goal_id  : {conv_result.goal_id}")
    if conv_result.status is ConversionStatus.DEDUPLICATED:
        print(
            "    NOTE: this (visitor, goal) was already converted — deduplicated."
        )
        print(
            "    Set CONVERT_DEMO_FORCE_MULTIPLE=1 to bypass dedup and send again."
        )
    elif conv_result.status is ConversionStatus.GOAL_NOT_FOUND:
        print(f"    NOTE: goal {GOAL_KEY!r} was not found in the loaded config.")
    print()

    if not is_live:
        print("[SDK] OFFLINE mode — no flush, no network. Output above is deterministic.")


# ---------------------------------------------------------------------------
# Experiment-preview link demonstration (qs-02) — shared by both modes
# ---------------------------------------------------------------------------

def _run_preview_demo(context: Any, *, is_live: bool) -> None:
    """Demonstrate experiment-preview links when CONVERT_DEMO_PREVIEW is set.

    A no-op when the env var is unset (default demo run is unaffected). When
    set, parses the canonical link value with ``parse_preview_param`` — a
    malformed value is shown taking the AC7 inert-with-warning path (no
    exception, no forced variation, the demo continues normally). A
    well-formed pair is force-decided via ``context.set_preview(...)`` and the
    two headline guarantees are proven with real output:

    1. The forced variation is served even though the target experience's
       variations are both non-running ('paused') — normal bucketing would
       NEVER serve it.
    2. Zero-trace: ``track_conversion`` on the previewed context returns
       ``tracked=False`` and performs no queue/persistence/network I/O; a
       DIFFERENT (non-previewed) experience on the SAME context still decides
       normally, proving preview isolation (AC5/AC6).
    """
    raw_preview = os.environ.get("CONVERT_DEMO_PREVIEW", "").strip()
    if not raw_preview:
        return

    print("=" * 60)
    print("Experiment-preview link demonstration (qs-02)")
    print("=" * 60)
    print(f"  CONVERT_DEMO_PREVIEW = {raw_preview!r}")
    print()

    pair = parse_preview_param(raw_preview)
    if pair is None:
        print(
            "  [WARN] Malformed preview param — parse_preview_param() returned None."
        )
        print(
            "         Expected 'convert_preview={experienceId}.{variationId}' with\n"
            "         dot-separated NUMERIC-ONLY ids, e.g.:\n"
            f"           CONVERT_DEMO_PREVIEW={_PREVIEW_EXAMPLE_LINK}"
        )
        print(
            "  Per AC7 (inert-on-bad-input), an application would simply skip\n"
            "  set_preview() here and continue normally — no exception is raised\n"
            "  and no variation is forced."
        )
        print()
        return

    experience_id, variation_id = pair
    print(f"  parsed pair : (experience_id={experience_id!r}, variation_id={variation_id!r})")
    print()

    context.set_preview(experience_id, variation_id)

    print(f"[P1] run_experience({PREVIEW_EXPERIENCE_KEY!r})  (the preview target's key)")
    preview_result = context.run_experience(PREVIEW_EXPERIENCE_KEY)
    if preview_result is not None:
        print(f"    variation_key  : {preview_result.variation_key}")
        print(f"    variation_id   : {preview_result.variation_id}")
        print(
            "    PROOF: both of this experience's variations carry status='paused'\n"
            "           (non-running) in the fixture, so normal run_experience()\n"
            "           would ALWAYS return None for this key. The preview link\n"
            "           forced this exact variation regardless, bypassing status,\n"
            "           audience, traffic allocation, and the bucketing hash\n"
            "           entirely."
        )
    else:
        print(
            "    result         : None -- set_preview() did not resolve "
            f"{experience_id!r}/{variation_id!r}\n"
            "                     (see the [WARN] preview_* diagnostic logged above)."
        )
        print(
            "    In OFFLINE mode the ids must match the fixture's built-in draft\n"
            f"    experience: {_PREVIEW_OFFLINE_EXPERIENCE_ID}."
            f"{_PREVIEW_OFFLINE_VARIATION_CONTROL_ID} (control) or "
            f"{_PREVIEW_OFFLINE_EXPERIENCE_ID}."
            f"{_PREVIEW_OFFLINE_VARIATION_TREATMENT_ID} (treatment)."
        )
    print()

    print(f"[P2] run_experience({EXPERIENCE_KEY!r})  (a DIFFERENT experience -- normal path)")
    normal_result = context.run_experience(EXPERIENCE_KEY)
    if normal_result is not None:
        print(
            f"    variation_key  : {normal_result.variation_key}  "
            "(unaffected by the active preview -- different experience key)"
        )
    else:
        print("    result         : None (unaffected by the active preview)")
    print()

    # force_multiple=True deliberately ISOLATES preview-suppression from
    # ordinary (visitor, goal) dedup: step [4] above already converted
    # GOAL_KEY on this same visitor/context, so WITHOUT force_multiple this
    # call would show tracked=False for the mundane reason of dedup even when
    # preview is NOT active -- making the preview guarantee ambiguous. With
    # force_multiple=True, a NON-preview context re-queues (tracked=True); a
    # preview-ACTIVE context still shows tracked=False regardless (PY-6:
    # unconditional suppression overrides force_multiple), unambiguously
    # proving preview zero-trace rather than routine dedup.
    print(
        f"[P3] track_conversion({GOAL_KEY!r}, force_multiple=True)  (zero-trace check)"
    )
    preview_conv = context.track_conversion(GOAL_KEY, revenue=1.0, force_multiple=True)
    print(f"    tracked : {preview_conv.tracked}")
    print(f"    status  : {preview_conv.status.value}")
    if preview_conv.tracked:
        print(
            "    Preview did NOT resolve (see above) -- force_multiple=True bypassed\n"
            "    ordinary dedup and queued normally, proving this is NOT preview\n"
            "    suppression when no preview is active."
        )
    else:
        print(
            "    Zero-trace: even with force_multiple=True, a preview-active context\n"
            "    performs NO dedup-marker read/write, NO queue enqueue, and NO\n"
            "    network I/O for track_conversion() -- an UNCONDITIONAL no-op,\n"
            "    unlike ordinary dedup (which force_multiple would bypass). Contrast\n"
            "    with the normal-path conversion in step [4] above, which queued/\n"
            "    tracked normally."
        )
    print()

    if is_live:
        print(
            "  NOTE: in LIVE mode, an experience_id absent from the locally fetched\n"
            "  config is resolved via the transport's '?exp=' fetch-through\n"
            "  (HttpxTransport.fetch_config_by_experience) -- set CONVERT_DEMO_PREVIEW\n"
            "  and CONVERT_DEMO_PREVIEW_EXPERIENCE_KEY to a real draft/paused staging\n"
            "  experience's numeric ids + key to preview it even though it was never\n"
            "  served in the fetched config."
        )
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    sdk_key = os.environ.get("CONVERT_SDK_KEY", "").strip()
    if sdk_key:
        auth_secret = os.environ.get("CONVERT_AUTH_SECRET") or None
        return run_live(sdk_key, auth_secret)
    return run_offline()


if __name__ == "__main__":
    sys.exit(main())
