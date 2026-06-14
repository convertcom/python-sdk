#!/usr/bin/env python3
"""Machine-derive the cross-SDK parity golden fixtures (Story 3.5 / qs-05).

This is the single, documented MAINTAINER entry point that (re)produces every
parity fixture consumed by ``tests/parity/``. It is dev/maintainer tooling that
lives OUTSIDE ``src/convert_sdk/`` and adds NO runtime dependency (``httpx``
remains the SDK's only runtime dep). It is needed ONLY at regeneration time —
``pytest tests/parity/`` itself loads the checked-in JSON and never spawns Node.

Drive strategy (qs-05 delegated the choice; resolved here)
----------------------------------------------------------
The generator drives Node oracle scripts under ``scripts/js_reference/``.
The bucketing oracle (``emit_bucketing.js``) uses the **real** npm
``murmurhash@^2.0.1`` package — the same package the JS SDK imports — so the
golden hash values are byte-exact against the real JS reference rather than a
hand port. That package encodes input strings as UTF-8 bytes via
``new TextEncoder().encode(value)`` and mixes in the UTF-8 byte length.
The other helpers (rules, features, state) are faithful ports of the JS SDK
source (``RuleManager`` + ``Comparisons``, ``DataManager`` entity lookup,
``SegmentsManager`` custom segments) and require no npm dependencies beyond
``murmurhash``.

Each emitted fixture file carries a top-level ``generated_from`` metadata block
identifying the JS SDK commit/version the vectors were derived from, so any
future drift is attributable to a specific reference revision. Regeneration is
deterministic and yields a clean ``git diff`` naming exactly which vectors
changed.

Usage::

    python scripts/generate_parity_fixtures.py            # regenerate all four
    python scripts/generate_parity_fixtures.py --check     # fail if out of date

Prerequisites: a Node runtime (any recent LTS); run ``npm install`` inside
``scripts/js_reference/`` to install ``murmurhash@^2.0.1`` before regenerating.
The ``NODE_PATH`` environment variable can also point to a pre-installed location.
See ``tests/parity/README.md``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
_JS_REF_DIR = Path(__file__).resolve().parent / "js_reference"
_FIXTURES_DIR = _REPO_ROOT / "tests" / "parity" / "fixtures"
_JS_SDK_DIR = (_REPO_ROOT.parent / "javascript-sdk").resolve()

# fixture filename -> (Node emitter script, human description)
_FAMILIES = {
    "bucketing_vectors.json": (
        "emit_bucketing.js",
        "MurmurHash3-32 bucketing hash (packages/bucketing + utils generateHash, seed 9999)",
    ),
    "rule_vectors.json": (
        "emit_rules.js",
        "RuleManager.isRuleMatched + Comparisons (packages/rules, packages/utils)",
    ),
    "feature_vectors.json": (
        "emit_features.js",
        "Feature resolution via bucketing + fullStackFeature change casting",
    ),
    "state_vectors.json": (
        "emit_state.js",
        "DataManager entity lookup + SegmentsManager custom segments (packages/data, packages/segments)",
    ),
}


def _js_sdk_revision() -> str:
    """Return the sibling JS SDK git revision (or a sentinel if unavailable)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_JS_SDK_DIR), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _run_node_emitter(script_name: str) -> List[Dict[str, Any]]:
    """Spawn a Node helper and parse its JSON-array stdout.

    Exits non-zero on any failure (missing Node, helper error, invalid JSON)
    rather than silently emitting empty/partial fixtures (qs-05 IO matrix).
    """
    script = _JS_REF_DIR / script_name
    if not script.exists():
        sys.stderr.write(f"ERROR: missing Node helper {script}\n")
        raise SystemExit(2)
    try:
        result = subprocess.run(
            ["node", str(script)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        sys.stderr.write(
            "ERROR: `node` not found. A Node runtime is required to REGENERATE "
            "parity fixtures (never to run the suite). See tests/parity/README.md\n"
        )
        raise SystemExit(2)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"ERROR: Node helper {script_name} failed (exit {exc.returncode}):\n{exc.stderr}\n"
        )
        raise SystemExit(2)
    try:
        vectors = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"ERROR: {script_name} produced invalid JSON: {exc}\n")
        raise SystemExit(2)
    if not isinstance(vectors, list) or not vectors:
        sys.stderr.write(
            f"ERROR: {script_name} produced no vectors (refusing to write an empty fixture)\n"
        )
        raise SystemExit(2)
    return vectors


def _build_fixture(script_name: str, description: str, js_rev: str) -> Dict[str, Any]:
    vectors = _run_node_emitter(script_name)
    return {
        "generated_from": {
            "reference": "Convert JavaScript SDK (../javascript-sdk)",
            "js_sdk_commit": js_rev,
            "derivation": description,
            "method": (
                "machine-derived by running a Node oracle script "
                f"(scripts/js_reference/{script_name}) backed by the real npm "
                "murmurhash@^2.0.1 package (UTF-8 via TextEncoder, byte-length mix); "
                "values are computed, never hand-authored"
            ),
            "generator": "scripts/generate_parity_fixtures.py",
        },
        "vectors": vectors,
    }


def _serialize(fixture: Dict[str, Any]) -> str:
    # ensure_ascii=False keeps Unicode vectors (e.g. 用户123) human-readable;
    # 2-space indent + trailing newline keeps a stable, clean git diff.
    return json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any fixture differs from a fresh regeneration",
    )
    args = parser.parse_args(argv)

    js_rev = _js_sdk_revision()
    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    stale: List[str] = []
    for filename, (script_name, description) in _FAMILIES.items():
        fixture = _build_fixture(script_name, description, js_rev)
        payload = _serialize(fixture)
        target = _FIXTURES_DIR / filename
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            # Compare vectors only (a differing js_sdk_commit alone is not drift).
            if current:
                cur_vec = json.loads(current).get("vectors")
                new_vec = fixture["vectors"]
                if cur_vec != new_vec:
                    stale.append(filename)
            else:
                stale.append(filename)
        else:
            target.write_text(payload, encoding="utf-8")
            sys.stdout.write(f"wrote {target.relative_to(_REPO_ROOT)} ({len(fixture['vectors'])} vectors)\n")

    if args.check:
        if stale:
            sys.stderr.write(
                "ERROR: parity fixtures are out of date; rerun the generator:\n  "
                + "\n  ".join(stale)
                + "\n"
            )
            return 1
        sys.stdout.write("all parity fixtures up to date\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
