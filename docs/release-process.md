# Release Process

Maintainer-facing reference for cutting a `convert-python-sdk` release. The
release pipeline is fully tag-driven: pushing `v<X.Y.Z>` to `main` triggers
the GitHub Actions workflow that re-runs CI, builds, publishes to PyPI via
OIDC Trusted Publishing, and creates a GitHub Release with the compiled
changelog.

## CI gates

`/.github/workflows/ci.yml` enforces the following on every PR and push:

| Gate                          | Frozen by                                  | Failure mode                                  |
| ----------------------------- | ------------------------------------------ | --------------------------------------------- |
| Ruff lint                     | `qs-02-ci-pipeline`                        | Blocks merge.                                 |
| mypy strict (`src/`)          | `qs-02-ci-pipeline`                        | Blocks merge.                                 |
| pytest matrix (15 cells)      | `qs-02-ci-pipeline`                        | Blocks merge per failing cell.                |
| Parity suite (`tests/parity`) | `qs-03-coverage-gate`, Story 3.5 fixtures  | Blocks merge — non-negotiable.                |
| Project coverage `>= 85%`     | `qs-03-coverage-gate`                      | Blocks merge.                                 |
| `evaluation/` coverage `>= 95%` | `qs-03-coverage-gate`                    | Blocks merge.                                 |
| Bounds-check (lower & upper)  | `qs-09-dependency-bounds-verification`     | Blocks merge per failing extreme.             |
| Changelog fragment (PRs only) | `qs-10-changelog-towncrier`                | Blocks PR if no `changes/<n>.<category>.md`.  |
| Build (wheel + sdist)         | `qs-02-ci-pipeline`                        | Blocks merge.                                 |

The matrix targets Python 3.9 → 3.13 across `ubuntu-latest`, `macos-latest`,
and `windows-latest`. `pytest` is pinned to the `8.4.x` line because pytest
9.x drops Python 3.9 support.

## Local pre-release verification

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/verify_release.py
```

This reproduces every CI gate locally (lint, types, full test run with both
coverage gates, parity suite, `uv build`). It exits non-zero on the first
failure and prints the failing command.

## Dependency bounds policy

Bounds policy is frozen by `qs-09-dependency-bounds-verification.md`:

1. **Runtime deps in `pyproject.toml` always carry compatible-release bounds**
   (`>=X,<Y`). Currently `httpx>=0.28,<0.29` is the only runtime dependency
   (Story 1.4 ships a pure-Python MurmurHash3 — no `mmh3` runtime dep).
2. **Exact lower-bound pins live only in `ci/lower-bounds-overrides.txt`.**
   The bounds-check CI job uses this file to install the oldest supported
   version of each runtime dep and re-runs the test suite. Both extremes
   must pass to merge.
3. **Widening bounds is a deliberate maintainer action.** Land it in a
   focused PR with a `changes/<n>.internal.md` (or `breaking` / `bugfix`
   if user-visible) fragment that explains the rationale.

## Changelog discipline

Every PR with user-visible behavior must add a fragment to `changes/`
(see `changes/README.md` for the naming convention). Fragments are
compiled by `towncrier build --yes --version <version>` at release time;
do not hand-edit `CHANGELOG.md` above the towncrier marker.

Internal-only PRs (CI, refactors, dependency bumps without behavior
changes) should still add a `changes/<n>.internal.md` fragment to keep
the missing-fragment CI gate green.

## Cutting a release

The end-to-end release path:

1. **Open a release PR** from `dev-branch` to `main` containing only the
   version bump in `pyproject.toml`. CI must be green.
2. **Land the PR** so `main` carries the bumped version.
3. **Tag and push:**
   ```bash
   git checkout main
   git pull
   git tag -a v0.1.0 -m "Release 0.1.0"
   git push origin v0.1.0
   ```
4. **Watch the release workflow** at
   `https://github.com/convertcom/python-sdk/actions/workflows/release.yml`.
   It re-runs CI, runs `towncrier build` to compile fragments into
   `CHANGELOG.md`, builds wheel + sdist, publishes to PyPI through OIDC
   Trusted Publishing, and creates a GitHub Release with the extracted
   notes.
5. **Verify the artifact** on
   [PyPI](https://pypi.org/project/convert-python-sdk/) and the GitHub
   Releases page.

### Pre-releases

Tags matching `vX.Y.Z(a|b|rc|dev)N` (e.g., `v0.2.0rc1`) are published with
the GitHub `--prerelease` flag and are surfaced on PyPI as pre-releases.

### One-time PyPI setup (already complete or to be configured)

Trusted Publishing on PyPI is configured per-project through the project
settings page on `pypi.org`. The publisher must reference:

| Field                | Value                                  |
| -------------------- | -------------------------------------- |
| PyPI project         | `convert-python-sdk`                   |
| Owner                | `convertcom`                           |
| Repository           | `python-sdk`                           |
| Workflow             | `release.yml`                          |
| Environment          | `pypi`                                 |

No long-lived PyPI token is ever stored as a repository secret; the OIDC
exchange happens during the publish job (`id-token: write`).

## Refreshing parity fixtures

Per `qs-05-parity-fixture-sourcing.md`, parity fixtures are checked in so
CI does not require a Node.js runtime at test time. Regeneration is a
maintainer action when the JavaScript SDK changes:

```bash
# From convert-python-sdk repo root, with the sibling javascript-sdk
# repo checked out at ../javascript-sdk on the desired commit.
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/generate_parity_fixtures.py
```

Inspect the resulting `git diff tests/parity/fixtures/` to confirm the
vector changes are intentional, then land them in a PR with a
`changes/<n>.internal.md` fragment recording the JS SDK commit they came
from.

## Troubleshooting

- **OIDC `403` from PyPI** — The Trusted Publisher entry on PyPI does not
  match the repo/workflow. Confirm owner, repo, workflow filename, and
  environment.
- **Coverage regressed below the gate** — Inspect `term-missing` output
  for the affected file and add direct unit tests. The
  `evaluation/` gate is independent of the project gate; both must pass.
- **Bounds-check failure on `lower`** — A new transitive constraint added
  upstream is incompatible with our declared minimum. Either pin a higher
  lower-bound in `pyproject.toml` (and add a `breaking`/`internal` fragment)
  or vendor a workaround.
- **Changelog-fragment check fails on a PR that genuinely has no
  user-visible effect** — Add a `changes/<pr-number>.internal.md` with one
  short sentence describing the maintenance.
