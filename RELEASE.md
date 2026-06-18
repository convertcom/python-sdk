# Release Process

This document describes how releases of the Convert Python SDK
(`convert-python-sdk`) are produced and what must be configured before the
release pipeline can run.

The short version: **every push to `main` whose Conventional Commit history
contains a `feat:`, `fix:`, or a `BREAKING CHANGE` triggers a new
release.** (`refactor:` commits appear in the release notes but do **not** by
themselves trigger a version bump.) The release workflow runs `semantic-release`, which writes the next
version into `src/convert_sdk/version.py` (a build-time, **uncommitted**
working-tree edit), builds the wheel + sdist, publishes to PyPI via **OIDC
Trusted Publishing**, then creates the `vX.Y.Z` git tag and a GitHub Release
with the generated notes.

No manual version bumping. No manual publishing. No long-lived PyPI API token.
Conventional commits drive everything, and there is **no `uv publish` or
`twine upload` command** — publishing happens only through the OIDC
`release.yml` workflow.

---

## Release Chain Overview

```
PR merged to main (squash merge → PR title becomes the commit subject)
  -> "CI" workflow runs (Ruff lint, mypy --strict, 15-cell test matrix,
     parity, bounds-check, build)
  -> "Release" workflow triggers via workflow_run AFTER CI succeeds
     (and only when the triggering event was a push to main)
    -> prepare job:
        -> semantic-release (dry-run) analyzes commits since the last v* tag:
          1. @semantic-release/commit-analyzer          → compute next version
          2. @semantic-release/release-notes-generator  → render markdown notes
          3. @semantic-release/exec (verifyReleaseCmd)  → export version + notes
                                                          to job outputs
        -> Stamp version into src/convert_sdk/version.py (UNCOMMITTED)
        -> uv build (wheel + sdist carrying the stamped version)
    -> publish-pypi job (needs: prepare):
        -> pypa/gh-action-pypi-publish (OIDC Trusted Publishing)
          → upload wheel + sdist to PyPI
    -> release job (needs: [prepare, publish-pypi]):
        -> semantic-release (real run):
          1-3. same as dry-run (deterministic — no commit landed since prepare)
          4. @semantic-release/exec (prepareCmd) → re-stamp version.py
          5. @semantic-release/github             → push vX.Y.Z tag + create
                                                    GitHub Release (via API)
```

The pipeline is **tag-only** — it pushes **no commit** to `main`. semantic-release
core pushes only the `vX.Y.Z` tag (a `refs/tags/*` ref, which the `main` branch
ruleset does not gate), and `@semantic-release/github` creates the Release via
the GitHub API. The version write in `src/convert_sdk/version.py` is a build-time
working-tree edit consumed by `uv build` (hatchling reads `__version__` via
`[tool.hatch.version] path`) and is **never committed**; the next release derives
its version from this run's git tag.

The plugin order above is **load-bearing** (defined in `release.config.mjs`).
**Publish-before-Release:** the `publish-pypi` job runs before the `release`
job (`needs: [prepare, publish-pypi]`). If the PyPI upload fails, the `release`
job is skipped — so no GitHub Release/tag is finalized without a corresponding
package on PyPI. The repo stays in its pre-release state and the next push
retries.

This release flow uses no `@semantic-release/git` and no
`@semantic-release/changelog` plugins (deliberately forbidden — they would commit
to `main` and ship a committed `CHANGELOG.md`). The changelog lives on **GitHub
Releases** (`[project.urls] Changelog` in `pyproject.toml` points there).

---

## Versioning & Conventional-Commit Map

semantic-release computes the next version with the standard
`@semantic-release/commit-analyzer` (`conventionalcommits` preset). Only
`feat:`, `fix:`, and `BREAKING CHANGE` bump the version; every other type is a
no-release (though some are still shown in the notes when a release is triggered
by one of those three):

| Commit type | Release type | In release notes |
|---|---|---|
| `fix:` | patch | Yes (Bug Fixes) |
| `feat:` | minor | Yes (Features) |
| `refactor:` | no release | Yes (Refactoring) — shown only |
| `BREAKING CHANGE:` footer / `!` marker | **major** | Yes |
| `chore:`, `docs:`, `ci:`, `test:`, `style:`, `perf:` | no release | No (hidden) |

The release-notes generator surfaces only `feat` / `fix` / `refactor` sections;
the maintenance types (`chore`, `docs`, `ci`, `test`, `style`, `perf`) are marked
hidden in `release.config.mjs` and never appear in the notes.

All tags use the `v` prefix (`v1.0.0`, `v1.2.3`) — `tagFormat: 'v${version}'`.

---

## One-Time Setup (Repo Admin)

These steps must be completed **before the first merge to `main`** that should
publish, otherwise the release workflow will fail.

### 1. Register the PyPI Trusted Publisher (OIDC)

PyPI OIDC Trusted Publishing lets the release workflow authenticate with a
short-lived, exchanged credential instead of a long-lived API key. Register the
trusted publisher on pypi.org once:

1. Sign in at <https://pypi.org>.
2. Create (or claim) the project `convert-python-sdk` if it does not exist yet
   (for a first publish, configure a *pending* publisher before the first
   upload).
3. Go to the project's **Settings → Publishing → Add a new publisher** (GitHub
   Actions), and enter:
   - **Owner / repository:** `convertcom/python-sdk`
   - **Workflow filename:** `release.yml`
   - **Environment name:** `pypi`
4. Save. From then on, the `release.yml` workflow running on
   `convertcom/python-sdk` within the `pypi` environment is trusted to publish
   `convert-python-sdk` with no stored API key.

There is **no `PYPI_API_TOKEN` secret anywhere** — `pypa/gh-action-pypi-publish`
performs the OIDC token exchange at run time.

### 2. Create the `pypi` GitHub Environment

The `publish-pypi` job runs inside the `pypi` GitHub Environment (required for
the OIDC subject claim to match the registered Trusted Publisher). Create it
once:

1. Repo → **Settings** → **Environments** → **New environment** → name it
   exactly `pypi`.
2. **Leave it with NO required reviewers and NO wait timers.** If the
   environment has a protection rule requiring a reviewer approval, the
   `publish-pypi` job will block waiting for approval — stalling every release.
   The OIDC exchange itself is the security boundary (not the environment
   protection rule).

### 3. Repository secrets

| Secret | Required | Source |
|---|---|---|
| `GITHUB_TOKEN` | yes (auto) | Provided automatically by GitHub Actions for every run — nothing to configure. Used by semantic-release core to push the `vX.Y.Z` tag and by `@semantic-release/github` to create the Release. |

That is the **complete** secret list. PyPI authentication is handled by OIDC
Trusted Publishing (step 1), so no PyPI API-key secret is stored.

### 4. Branch-protection required checks

Configure branch protection on `main` (Repo → **Settings** → **Branches** →
add/edit the `main` rule) to require these status checks to pass before merge.
The names below are the **exact job names** from the workflows — quote them
verbatim:

From the **CI** workflow (`.github/workflows/ci.yml`):

- `PR title (Conventional Commits)`
- `Ruff lint`
- `mypy --strict`
- `test (py3.9 / ubuntu-latest)`, `test (py3.9 / macos-latest)`,
  `test (py3.9 / windows-latest)`, `test (py3.10 / ubuntu-latest)`, …
  (all 15 matrix cells: Python 3.9–3.13 × {ubuntu, macos, windows})
- `bounds-check (lower)`, `bounds-check (upper)`
- `build (wheel + sdist)`

---

## Triggering a Release

Releases are fully automatic. The process:

1. Open a PR containing one or more conventional commits. This repo is
   **squash-merge only**, so the **PR title** becomes the squash commit subject
   and must itself be a valid Conventional Commit (CI validates it via the
   `PR title (Conventional Commits)` job).
2. Merge the PR to `main`. GitHub fires the **CI** workflow
   (`.github/workflows/ci.yml`).
3. On CI success, GitHub fires the **Release** workflow
   (`.github/workflows/release.yml`) via a `workflow_run` trigger
   (`workflows: ['CI']`, `branches: [main]`).
4. semantic-release analyzes every commit on `main` since the last `v*` tag and
   applies the version/notes map above.
5. If a release-worthy commit exists, the pipeline stamps the version into
   `src/convert_sdk/version.py`, builds the wheel + sdist, publishes to PyPI
   via OIDC, then pushes the `vX.Y.Z` tag and creates the GitHub Release. If
   nothing is release-worthy (only `chore`/`docs`/`ci`/`test`/…), the workflow
   succeeds silently with no release.

**No manual publish step.** You never bump the version or run `uv publish` by
hand — write an accurate PR title and the pipeline does the rest on merge.

---

## Previewing a Release: Dry Run

`yarn release:dry-run` runs semantic-release in dry-run mode
(`semantic-release --dry-run --no-ci`). It will:

- Analyze commits since the last tag.
- Decide the next version.
- Show the rendered release notes.
- **Not** write `version.py`, **not** build or publish, **not** tag.

semantic-release checks the current branch against the `branches` entry in
`release.config.mjs` (currently `['main']`). On `main`, the dry-run prints the
next-version plan. On any other branch it exits with:

```
This test run was not triggered in a known release branch
```

That message is **expected** — it confirms the config parses. To exercise a full
dry-run on a feature branch, temporarily add the branch name to
`release.config.mjs`'s `branches` array, run the dry-run, then discard the
temporary edit before committing:

```bash
# On main:
yarn release:dry-run

# On a feature branch (full dry-run):
# 1. Edit release.config.mjs → branches: ['main', 'feature/my-branch']
# 2. yarn release:dry-run
# 3. discard the temporary edit to release.config.mjs (do NOT commit it)
```

The branch must exist on `origin` (semantic-release needs `git ls-remote`); push
first if it is local-only.

---

## First Release (v1.0.0)

The first release is produced automatically by the pipeline — no manual tagging.
On the first merge to `main` after the release workflow is configured,
semantic-release observes that no prior `v*` tag exists, so it:

1. Treats every releasable commit in history (all `feat:` / `fix:` /
   `BREAKING CHANGE` since project inception) as part of the first release.
2. Emits `v1.0.0` as the version (semantic-release's fixed first-release
   default).
3. Generates a release-notes block covering the full history, grouped by commit
   type.
4. Stamps `1.0.0` into `src/convert_sdk/version.py` (uncommitted), runs
   `uv build`, publishes to PyPI, then pushes the `v1.0.0` tag and publishes a
   GitHub Release on it.

`src/convert_sdk/version.py` ships with `__version__ = "0.0.0"` as a dev
placeholder — the first release overwrites it at build time (and never commits
the change). Do **not** create a `v1.0.0` tag manually before or after the first
merge — the pipeline owns this, and a pre-existing tag will be raced or block
the automated tag push.

---

## Fork-PR Safeguard (DO NOT REMOVE)

The release workflow's `if:` guard on the `prepare` job carries two conditions,
both required:

```yaml
if: >
  github.event.workflow_run.conclusion == 'success' &&
  github.event.workflow_run.event == 'push'
```

The **second** condition — `github.event.workflow_run.event == 'push'` — is
critical. `workflow_run` fires on every completed CI run, including runs
triggered by pull requests. Fork PRs run with no secret/OIDC access, so
without this guard a fork PR's CI run would also fire the release workflow,
which would either:

1. Fail noisily (no OIDC token to exchange), cluttering the PR with red
   cross-marks, or — worse —
2. Under certain misconfigurations, leak into the PR's logs.

Always keep the `push` check. If you are ever tempted to remove it because
"release ran twice for one push", the answer is almost certainly a different fix
(concurrency groups — the workflow already uses `concurrency: { group: release,
cancel-in-progress: false }`), not weakening this guard.

---

## Rollback Procedure

**Published PyPI versions cannot be silently replaced.** Once
`convert-python-sdk X.Y.Z` is uploaded, re-uploading the same version is
rejected. If a bad release slips through:

1. Do **not** try to overwrite the version.
2. Push a conventional `fix:` commit that addresses the problem. The next
   release workflow publishes a new patch version (e.g. if `v1.2.3` was bad,
   the fix ships as `v1.2.4`).
3. If the bad version must be made un-installable, **yank** it via the PyPI
   project web UI or the PyPI API:
   - Go to <https://pypi.org/manage/project/convert-python-sdk/releases/> and
     yank the specific version (PyPI → project page → release → "Yank release").
   - Alternatively, use the PyPI API with an API token (unlike `gem yank`,
     PyPI has no CLI yank command included in standard tooling).
   - Yanking removes the version from the index so it can no longer be resolved
     by `pip install`, but the artifact is not deleted and the version number
     can never be reused. Prefer shipping a forward fix (`fix:`) over yanking
     unless the release is actively harmful.

---

## Quality Gates

Every PR and every push to `main` runs `.github/workflows/ci.yml`. Run all gates
locally in one command:

```bash
# Requires the dev group: uv sync --group dev
python scripts/verify_release.py
# Skip the slow build step while iterating:
python scripts/verify_release.py --skip-build
```

| Gate | Tool | Threshold / rule |
|------|------|------------------|
| Lint | Ruff (`E/W/F/B/SIM/RUF`, line-length 100) | Any finding on `src/` blocks merge |
| Type-check | mypy `--strict` (the package) | Any error blocks merge |
| Tests | pytest, 15-cell matrix (Python 3.9-3.13 × {ubuntu, macos, windows}) | Any failing cell blocks merge |
| Coverage (project) | pytest-cov | `--cov-fail-under=85` — **fails**, not warns |
| Coverage (evaluation) | coverage report | `evaluation/` modules ≥ **95%** — fails, not warns |
| Parity | pytest `tests/parity/` | 100% pass — **release-blocking** (see below) |
| Dependency bounds | uv (lower/upper) | Both edges must pass (see below) |
| Build | `uv build` | Wheel + sdist must build |

### Coverage and parity gates

- **Coverage must fail, never warn.** The project floor is 85% across
  `src/convert_sdk/`; the evaluation core (`evaluation/`) carries a stricter 95%
  floor because it is the cross-SDK-critical bucketing/rule/feature engine.
- **Parity is release-blocking.** `tests/parity/` runs the Python SDK's real
  evaluation surfaces against checked-in JavaScript-reference golden vectors. A
  divergence on a parity-critical field is a release blocker, not an advisory.
- Do **not** add `# pragma: no cover` to evaluation or parity code without an
  explicit, reviewed justification.

### Updating parity coverage as JavaScript contracts evolve

When the JavaScript SDK's behavior or contracts change:

1. Ensure the sibling JavaScript SDK is checked out at `../javascript-sdk`.
2. Regenerate the golden vectors from the JS reference:

   ```bash
   python scripts/generate_parity_fixtures.py
   ```

3. Run the parity suite to confirm the Python SDK still matches:

   ```bash
   uv run pytest tests/parity -x
   ```

4. If a parity-critical field diverged, fix the Python implementation (never
   the fixture) until the suite is green, and open a PR with a `fix:` commit.

### Dependency bounds

`httpx` is the SDK's **only** runtime dependency (the bucketing layer ships a
pure-Python MurmurHash3 — there is no hashing dependency). `pyproject.toml`
declares a compatible-release **range** (`httpx>=0.28,<1.0`); exact lower-bound
pins live **only** in `ci/lower-bounds-overrides.txt`.

CI verifies both edges of the declared range in the `bounds-check` job:

- **Lower bound** — installs `httpx==0.28.0` on Python 3.9 and runs the unit +
  integration suite.
- **Upper bound** — resolves the newest compatible versions on Python 3.13 and
  runs the same suite.

**Widening bounds is a deliberate maintainer action**: confirm the upstream
changelog, update the range in `pyproject.toml` and the pin in
`ci/lower-bounds-overrides.txt`, and let the bounds-check job validate both
edges.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `release.yml` didn't run after a merge to `main` | CI failed, or the triggering event wasn't a push, or the commits were all non-release types. | Check the Actions tab — the Release workflow only proceeds when CI concluded `success` AND the event was `push`. If CI failed, fix that. If the commits were `chore:`/`docs:`, no release is expected. |
| Release ran but published nothing | No release-worthy commit since the last tag (only `chore`/`docs`/`ci`/`test`/`style`/`perf`). | Expected — semantic-release succeeds silently with no version. Land a `feat:`/`fix:` to publish. |
| `pypa/gh-action-pypi-publish` OIDC auth error | The PyPI Trusted Publisher is not registered, or the repo/workflow/environment in the registration doesn't match `convertcom/python-sdk` ↔ `release.yml` ↔ `pypi`. | Re-check the trusted-publisher entry on pypi.org (One-Time Setup step 1). The `pypi` environment must exist (step 2). |
| GitHub Release/tag created but package missing on PyPI | Should not happen — `publish-pypi` runs before `release` (`needs: [prepare, publish-pypi]`). If you see it, a manual tag was likely pushed out of band. | Do not hand-create `v*` tags. Let the pipeline own tagging. |
| `yarn release:dry-run` prints "This test run was not triggered in a known release branch" | Expected on any branch except `main`. | To force a full dry-run on a feature branch, temporarily add the branch to `release.config.mjs`'s `branches` array (discard before committing). On `main`, this means the local branch isn't pushed to `origin` — push first. |
| `Cannot find module '<preset>'` from a semantic-release plugin | The yarn node linker isn't producing a `node_modules/` tree the dynamic preset import can walk. | Confirm `.yarnrc.yml` contains `nodeLinker: node-modules` and re-run `yarn install --immutable`. |
