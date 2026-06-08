# Cross-SDK Parity Harness (`tests/parity/`)

This directory holds the **cross-SDK parity validation harness** for the Convert
Python SDK. It proves the Python SDK's behavior is byte-/value-exact with the
JavaScript SDK (the behavioral reference implementation) for the shared
evaluation surfaces. It claims **NFR20** (cross-SDK parity tests pass 100%) and
**FR30** (teams can validate Python behavior against the JavaScript reference).

The JavaScript SDK is the source of truth. Parity is a **release gate**, not
optional coverage: if a parity vector diverges, that is a real drift signal owned
by the responsible evaluation module — never a license to edit a fixture to make
a test pass.

## Layout

```
tests/parity/
├── conftest.py                       # @pytest.fixture JSON loaders (one per family)
├── README.md                         # this file
├── fixtures/
│   ├── bucketing_vectors.json        # MurmurHash3-32 hash vectors (seed 9999)
│   ├── rule_vectors.json             # RuleManager / Comparisons vectors
│   ├── feature_vectors.json          # feature-resolution vectors
│   └── state_vectors.json            # entity-lookup + custom-segment vectors
├── test_js_bucketing_parity.py       # bucketing parity (Story 1.4 baseline)
├── test_js_rule_parity.py            # rule-evaluation parity (Story 1.4 surface)
├── test_js_feature_parity.py         # feature-resolution parity (Story 1.5/1.6 surface)
└── test_js_state_parity.py           # state/entity-lookup + segment parity (Story 3.3/3.4)
```

Fixtures live ONLY under `fixtures/` as external checked-in JSON. They are NEVER
inlined in a test file and NEVER hand-authored — every vector is machine-derived
by the generator (see below). Each test loads its vectors through the matching
`conftest.py` loader (`bucketing_vectors`, `rule_vectors`, `feature_vectors`,
`state_vectors`).

## Running the suite

The suite runs **offline** and **with no JavaScript runtime present** — it loads
only the checked-in JSON and exercises the pure-Python SDK. No Node, no network.

```bash
# from the repo root
.venv/bin/python -m pytest tests/parity/            # all families
.venv/bin/python -m pytest tests/parity/test_js_rule_parity.py   # one family
```

`pytest tests/parity/` passing 100% is the NFR20 release gate. The Story 5.1 CI
workflow (which this story does NOT author) calls this selection as-is across the
Python 3.9–3.13 × {Ubuntu, macOS, Windows} matrix; the fixtures and tests are
portable across it (pure-Python hash, no compiled extension).

## Regenerating the fixtures (maintainers)

A **Node runtime is required ONLY for regeneration**, never to run the suite.

```bash
# Prerequisites:
#   * Node (any recent LTS) on PATH — `node --version`
#   * the sibling ../javascript-sdk checkout next to this repo
#     (its node_modules are NOT required — see "How derivation works" below)

python scripts/generate_parity_fixtures.py          # (re)write all four fixtures
python scripts/generate_parity_fixtures.py --check    # CI-style: non-zero if stale
```

`scripts/generate_parity_fixtures.py` is the **single sanctioned entry point** and
the only sanctioned author of golden values. It is maintainer/dev tooling that
lives OUTSIDE `src/convert_sdk/` and adds NO runtime dependency (`httpx` remains
the SDK's only runtime dep).

### How derivation works (drive strategy)

The Python generator drives the JS reference by spawning small, **dependency-free
Node helper scripts** under `scripts/js_reference/`. Each helper is a byte-faithful
transcription of the corresponding JavaScript SDK source:

| Helper | Faithful port of |
|--------|------------------|
| `bucketing.js` / `emit_bucketing.js` | `packages/bucketing` + `packages/utils/string-utils.ts` `generateHash` (npm `murmurhash` v3, seed 9999) |
| `rule_engine.js` / `emit_rules.js` | `packages/rules/rule-manager.ts` + `packages/utils/comparisons.ts` |
| `emit_features.js` | feature resolution: bucketing + `fullStackFeature` change casting |
| `emit_state.js` | `packages/data/data-manager.ts` entity lookup + `packages/segments/segments-manager.ts` |

Because the helpers are faithful PORTS, the golden values are **computed by
running the same algorithm the JS SDK runs** — they are machine-derived, never
hand-authored. A faithful port (rather than importing the TypeScript packages
directly) is used because the JS SDK ships TypeScript and its `node_modules` are
not assumed to be installed; a bare Node install is sufficient. The generator
exits non-zero if a helper fails or produces no vectors (it never writes an
empty/partial fixture).

### Provenance (`generated_from`)

Every fixture file carries a top-level `generated_from` block naming the JS SDK
commit it was derived from:

```json
"generated_from": {
  "reference": "Convert JavaScript SDK (../javascript-sdk)",
  "js_sdk_commit": "34f0a7a461722e628d28db88dc8098ed089efbfe",
  "derivation": "...",
  "method": "machine-derived by running a dependency-free faithful Node port ...",
  "generator": "scripts/generate_parity_fixtures.py"
}
```

Regeneration is deterministic and yields a **clean `git diff` naming exactly which
vectors changed**. **Hand-editing a fixture is forbidden** — if a value is wrong,
fix the generator (or the JS reference port) and regenerate. The `--check` mode
compares the `vectors` arrays only, so a differing `js_sdk_commit` alone is not
treated as drift.

## Reading a failure (AC #3)

Each parity assertion is diagnostic. On a divergence the message names the fixture
file, the entry id, the actual Python value, and the expected JS value, e.g.:

```
AssertionError: rule parity divergence in rule_vectors.json [equals_hit_ci]:
data={'country': 'us'} -> python=True != js=False
```

This makes the drift unambiguous and attributable to the responsible evaluation
surface (bucketing → Story 1.4, rules → Story 1.4, features → Story 1.5/1.6,
state/entity-lookup → Story 3.3/3.4). Resolve drift in the owning module, not by
editing a fixture.

## Scope and related parity work

- **Tracking-payload parity** (`tracking_payloads.json` /
  `test_js_tracking_payload_parity.py`) is owned by **NFR21 / Story 2.2**, NOT this
  harness. It is intentionally not authored or duplicated here.
- **CI wiring** (the `.github/workflows/` parity/coverage gate YAML) is owned by
  **Story 5.1** (qs-02/qs-03). This harness only guarantees `pytest tests/parity/`
  is discoverable and 100% green so that pipeline can call it as-is. Whether the
  generator should additionally run as a CI drift-detection check (`--check`) is an
  Ask-First decision left to Story 5.1.
- **FR50 typed-reason result taxonomy** is deferred to **Story 4.2**. The state
  vectors here encode the Story-3.4 `None`/empty no-match form (multi-key/id skips
  unknowns), NOT the typed-reason object.
