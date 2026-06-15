# Convert Python SDK — Manual-Verification Demo Harness

A small, framework-agnostic, stdlib-only runner that lets you verify the SDK
end-to-end against a real backend. Two modes, **OFFLINE as the default**.

## Quick start

```
# OFFLINE (default — zero credentials, deterministic, no network):
python demo/run_demo.py

# LIVE (opt-in — fetches real config from staging, delivers a real conversion):
CONVERT_SDK_KEY=10035569/10034190 python demo/run_demo.py
```

---

## OFFLINE mode (default)

No credentials, no network. The SDK is initialized from the committed
`demo/config_fixture.json` which carries the **real** staging entity keys
(not invented placeholders). Output is deterministic for the fixed visitor
`demo-visitor-001`.

**Run:**

```
python demo/run_demo.py
```

**Expected output (verbatim, deterministic):**

```
============================================================
Convert Python SDK — OFFLINE demo
============================================================
  config:   demo/config_fixture.json (committed fixture)
  visitor:  'demo-visitor-001' (fixed, deterministic)

[SDK] Ready (direct config, no network)

[1] run_experience('test-experience-ab-fullstack-1')
    experience_key : test-experience-ab-fullstack-1
    variation_key  : variation-treatment
    variation_id   : demo-var-treatment

[2] run_feature('test-feature-rollout-1')
    feature_key    : test-feature-rollout-1
    status         : enabled
    variables:
      enabled: True  (type=bool)
      headline: 'Exclusive offer just for you!'  (type=str)
      button_color: 'green'  (type=str)
      max_items: 10  (type=int)
    via experience : test-experience-ab-fullstack-1
    via variation  : variation-treatment

[3] set_segments({'test-segment-1': True})
    default_segments: {'test-segment-1': True}

[4] track_conversion('button-primary-click', revenue=29.99, force_multiple=False)
    status   : queued
    tracked  : True
    goal_key : button-primary-click
    goal_id  : goal-primary-click

[SDK] OFFLINE mode — no flush, no network. Output above is deterministic.
```

### What the OFFLINE run verifies

| Step | What it proves |
|------|---------------|
| `run_experience` returns `variation-treatment` | Deterministic bucketing (MurmurHash3) maps `demo-visitor-001` to the second 50% bucket for this experience |
| `run_feature` returns `status=enabled` + typed vars | Feature variable type-casting works (`bool`, `str`, `int`) |
| `set_segments` + `default_segments` persisted | Visitor segment state stored and readable |
| `track_conversion` returns `status=queued` | Goal resolves and event is enqueued (no network in OFFLINE) |

---

## LIVE mode (opt-in)

Fetches real config from the shared Convert staging project over HTTPS, buckets
the visitor, and delivers a real conversion to the staging tracking endpoint.

### Requirements

- Access to the shared staging project `10035569/10034190`
- `CONVERT_SDK_KEY` set to `10035569/10034190` (public, no secret required for
  the shared project)

### Setup

Copy `.env.example` to `demo/.env` (never committed — listed in `.gitignore`)
and uncomment the `CONVERT_SDK_KEY` line:

```
cp demo/.env.example demo/.env
# edit demo/.env and uncomment: CONVERT_SDK_KEY=10035569/10034190
```

Or pass the key inline:

```
CONVERT_SDK_KEY=10035569/10034190 python demo/run_demo.py
```

### What LIVE mode does

1. Fetches `GET /api/v1/config/10035569/10034190?environment=staging` from
   `https://cdn-4-staging.convertexperiments.com` — a 200 proves the config
   route is correct (guards the PR #46 class of 404).
2. Buckets the visitor into `test-experience-ab-fullstack-1`.
3. Resolves `test-feature-rollout-1` and prints typed variables.
4. Attaches the `test-segment-1` segment.
5. Fires `track_conversion("button-primary-click", revenue=29.99)`.
6. Flushes the queue and reports the tracking endpoint HTTP status.

### Verifying the conversion in the staging dashboard

After a successful LIVE run, open the Convert staging dashboard for project
`10034190` and check:

1. **Live Log** (top nav) — look for the visitor id printed by the run
   (default `demo-visitor-001`) with the goal `button-primary-click`.
2. **Conversions** report — the conversion should appear within a few seconds
   of the flush.

### Re-running (dedup)

By default the SDK deduplicates `(visitor_id, goal_id)` — a repeat run for the
same visitor prints `status: deduplicated`. To force another delivery:

```
CONVERT_SDK_KEY=10035569/10034190 CONVERT_DEMO_FORCE_MULTIPLE=1 python demo/run_demo.py
```

Or change the visitor id:

```
CONVERT_SDK_KEY=10035569/10034190 CONVERT_DEMO_VISITOR_ID=demo-visitor-002 python demo/run_demo.py
```

---

## Ground truth — cited entity keys

All keys below come from the JS and PHP reference demos; none are invented.

| Entity | Key | Source |
|--------|-----|--------|
| SDK key (public) | `10035569/10034190` | `../javascript-sdk/demo/nodejs/app.js:32`; `../php-sdk/demo/laravel/.env.example` |
| Experience | `test-experience-ab-fullstack-1` | `../javascript-sdk/demo/nodejs/routes/events.js` (`experienceKey`) |
| Feature rollout | `test-feature-rollout-1` | `../javascript-sdk/demo/nodejs/routes/events.js` (`featureRolloutKey`) |
| Segment | `test-segment-1` | `../javascript-sdk/demo/nodejs/routes/events.js` (`segmentsKey`) |
| Goal | `button-primary-click` | `../php-sdk/demo/laravel/config/convert.php` (`goal_key`) |
| Config host (staging) | `https://cdn-4-staging.convertexperiments.com` | `scripts/verify_staging_transaction.py`; `src/convert_sdk/config.py` |

---

## File map

| File | Purpose |
|------|---------|
| `demo/run_demo.py` | Dual-mode runner — OFFLINE or LIVE based on `CONVERT_SDK_KEY` |
| `demo/config_fixture.json` | Committed OFFLINE config with real staging entity keys |
| `demo/.env.example` | Template — copy to `demo/.env` for LIVE credentials |
| `demo/.env` | Gitignored — never committed; holds real `CONVERT_SDK_KEY` |
| `demo/README.md` | This file |
