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

## Testing preview links (qs-02)

An **experiment-preview link** forces one specific variation on a single
`Context`, bypassing every normal qualification/bucketing gate for that
experience — audience, location, experience/variation status, traffic
allocation, and the visitor's own deterministic bucketing hash. It also
guarantees **zero trace**: no tracking event is enqueued and no visitor state
is persisted for the previewed context (`Context.set_preview`,
`convert_sdk.parse_preview_param`).

`demo/config_fixture.json` ships a dedicated preview-only experience built
specifically to demonstrate this — **the killer proof point**: this experience
can **never** be served by normal bucketing, because both of its variations
carry `status: "paused"` (non-running). Only a preview link renders it.

| Entity | id | key | status |
|--------|----|----|--------|
| Experience | `900210001` | `preview-only-draft-experience` | `draft` |
| Variation (control) | `900210101` | `variation-control-draft` | `paused` |
| Variation (treatment) | `900210102` | `variation-treatment-draft` | `paused` |

Its ids are **numeric** (unlike the string placeholder ids on the primary demo
experience) because the canonical link format —
`convert_preview={experienceId}.{variationId}` — requires dot-separated
numeric-only segments; `parse_preview_param` rejects anything else.

### Run it

```
CONVERT_DEMO_PREVIEW=900210001.900210101 python demo/run_demo.py
```

**Expected output (appended after the normal arc above):**

```
============================================================
Experiment-preview link demonstration (qs-02)
============================================================
  CONVERT_DEMO_PREVIEW = '900210001.900210101'

  parsed pair : (experience_id='900210001', variation_id='900210101')

[P1] run_experience('preview-only-draft-experience')  (the preview target's key)
    variation_key  : variation-control-draft
    variation_id   : 900210101
    PROOF: both of this experience's variations carry status='paused'
           (non-running) in the fixture, so normal run_experience()
           would ALWAYS return None for this key. The preview link
           forced this exact variation regardless, bypassing status,
           audience, traffic allocation, and the bucketing hash
           entirely.

[P2] run_experience('test-experience-ab-fullstack-1')  (a DIFFERENT experience -- normal path)
    variation_key  : variation-treatment  (unaffected by the active preview -- different experience key)

[P3] track_conversion('button-primary-click', force_multiple=True)  (zero-trace check)
    tracked : False
    status  : deduplicated
    Zero-trace: even with force_multiple=True, a preview-active context
    performs NO dedup-marker read/write, NO queue enqueue, and NO
    network I/O for track_conversion() -- an UNCONDITIONAL no-op,
    unlike ordinary dedup (which force_multiple would bypass). Contrast
    with the normal-path conversion in step [4] above, which queued/
    tracked normally.
```

**What this proves:**

1. **The forced draft variation is served even though normal bucketing never
   would be** — `[P1]` returns `variation-control-draft` for an experience
   whose variations are both non-running.
2. **A different experience on the same context is unaffected** — `[P2]`
   still buckets `test-experience-ab-fullstack-1` normally, proving preview
   isolation is scoped to the targeted experience only.
3. **Zero trace** — `[P3]` passes `force_multiple=True` *deliberately*: this
   isolates preview suppression from ordinary `(visitor, goal)` dedup (the
   goal was already converted once in step `[4]` of the normal arc). If
   `tracked=False` were just routine dedup, `force_multiple=True` would
   bypass it and show `tracked=True`. It stays `False` — proof this is the
   SDK's unconditional preview suppression, not dedup.

Try the other variation to see the opposite arm forced:

```
CONVERT_DEMO_PREVIEW=900210001.900210102 python demo/run_demo.py
```

### Malformed input (inert, never raises)

```
CONVERT_DEMO_PREVIEW=garbage python demo/run_demo.py
```

```
[WARN] Malformed preview param — parse_preview_param() returned None.
       Expected 'convert_preview={experienceId}.{variationId}' with
       dot-separated NUMERIC-ONLY ids, e.g.:
         CONVERT_DEMO_PREVIEW=900210001.900210101
Per AC7 (inert-on-bad-input), an application would simply skip
set_preview() here and continue normally — no exception is raised
and no variation is forced.
```

`1.2.3` (a second dot) and any non-numeric segment behave identically — this
is `parse_preview_param`'s AC9 contract, not something the demo re-implements.

An id pair that parses but doesn't resolve to anything in the loaded config
(e.g. `CONVERT_DEMO_PREVIEW=999999.888888`) takes the same inert path: a
`[WARN] preview_unresolvable_experience` diagnostic is logged, `run_experience`
for the preview key returns `None`, and — proving the contrast above —
`track_conversion(..., force_multiple=True)` in `[P3]` shows `tracked=True`
(ordinary queuing resumes, because no preview is actually active).

### LIVE mode

The same `CONVERT_DEMO_PREVIEW` env var works in LIVE mode. Set
`CONVERT_DEMO_PREVIEW_EXPERIENCE_KEY` to the **key** of the real staging
draft/paused experience you want to preview (the demo has no way to infer a
real experience's key from its numeric ids alone):

```
CONVERT_SDK_KEY=10035569/10034190 \
CONVERT_DEMO_PREVIEW=<realExperienceId>.<realVariationId> \
CONVERT_DEMO_PREVIEW_EXPERIENCE_KEY=<realExperienceKey> \
python demo/run_demo.py
```

If `<realExperienceId>` isn't present in the config LIVE mode already fetched,
the SDK resolves it via the transport's `?exp=` fetch-through
(`HttpxTransport.fetch_config_by_experience`) — so you can preview a draft
experience that was never served in the fetched config at all.

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
| `demo/run_demo.py` | Dual-mode runner — OFFLINE or LIVE based on `CONVERT_SDK_KEY`; also wires the preview-link demonstration (`CONVERT_DEMO_PREVIEW`) |
| `demo/config_fixture.json` | Committed OFFLINE config with real staging entity keys, plus a dedicated draft/paused preview-only experience (`preview-only-draft-experience`) |
| `demo/.env.example` | Template — copy to `demo/.env` for LIVE credentials |
| `demo/.env` | Gitignored — never committed; holds real `CONVERT_SDK_KEY` |
| `demo/README.md` | This file |
