# Release process (maintainers)

This document is the repeatable, end-to-end release workflow for the Convert
Python SDK. It ties together the five frozen quick specs that govern release
discipline: CI (qs-02), coverage and parity gates (qs-03), dependency-bounds
verification (qs-09), changelog management (qs-10), and tag-triggered PyPI
publishing (qs-11).

The distribution name on PyPI is **`convert-python-sdk`**; the import package is
**`convert_sdk`**. The version is single-sourced from
`src/convert_sdk/version.py`.

## At a glance

1. Land all feature work on `main` (each PR carries a `changes/` fragment).
2. Bump `__version__` in `src/convert_sdk/version.py`.
3. Run the gates locally: `python scripts/verify_release.py --version X.Y.Z`.
4. Open and merge the version-bump PR (CI must be green).
5. Tag the merge commit `vX.Y.Z` and push the tag.
6. The release workflow publishes to PyPI (OIDC) and creates a GitHub Release.

## Quality gates

Every PR and every push to `main` runs `.github/workflows/ci.yml`. A release tag
re-runs the **entire** CI pipeline as a gate before anything is published — a
failure anywhere (lint, type-check, any matrix cell, bounds-check, build) stops
the publish.

| Gate | Tool | Threshold / rule |
|------|------|------------------|
| Lint | Ruff (`E/W/F/B/SIM/RUF`, line-length 100) | Any finding on `src/` blocks merge |
| Type-check | mypy `--strict` (the package) | Any error blocks merge |
| Tests | pytest, 15-cell matrix (Python 3.9-3.13 × {ubuntu, macos, windows}) | Any failing cell blocks merge |
| Coverage (project) | pytest-cov | `--cov-fail-under=85` — **fails**, not warns |
| Coverage (evaluation) | coverage report | `evaluation/` modules ≥ **95%** — fails, not warns |
| Parity | pytest `tests/parity/` | 100% pass — **release-blocking** (see below) |
| Dependency bounds | uv (lower/upper) | Both edges must pass (see below) |
| Changelog | towncrier `check` | PRs touching the package must add a fragment |
| Build | `uv build` | Wheel + sdist must build |

Reproduce all of these locally in one shot:

```bash
# Requires the dev group: uv sync --group dev
python scripts/verify_release.py --version 0.1.0
# Skip the slow build step while iterating:
python scripts/verify_release.py --version 0.1.0 --skip-build
```

`verify_release.py` exits non-zero if any gate fails and prints a per-gate
PASS/FAIL summary. It is the maintainer's local mirror of CI.

## Coverage and parity gates (qs-03)

- **Coverage must fail, never warn.** The project floor is 85% across
  `src/convert_sdk/`; the evaluation core (`evaluation/`) carries a stricter 95%
  floor because it is the cross-SDK-critical bucketing/rule/feature engine.
- **Parity is release-blocking.** `tests/parity/` runs the Python SDK's real
  evaluation surfaces against checked-in JavaScript-reference golden vectors
  (Story 3.5 infrastructure). A divergence on a parity-critical field is a
  release blocker, not an advisory — the suite runs JS-runtime-free against the
  committed `tests/parity/fixtures/*.json`.
- Do **not** add `# pragma: no cover` to evaluation or parity code without an
  explicit, reviewed justification.

## Updating parity coverage as JavaScript contracts evolve (qs-05, FR57)

When the JavaScript SDK's behavior or contracts change, the Python SDK's parity
coverage is updated and revalidated through this workflow — it does not require
new bespoke tooling.

1. Ensure the sibling JavaScript SDK is checked out at `../javascript-sdk`.
2. Regenerate the golden vectors from the JS reference:

   ```bash
   python scripts/generate_parity_fixtures.py
   ```

   This refreshes `tests/parity/fixtures/*.json` from the JS reference
   implementations under `scripts/js_reference/`.
3. Run the parity suite to confirm the Python SDK still matches:

   ```bash
   uv run pytest tests/parity -x
   ```
4. If a parity-critical field diverged, fix the Python implementation (never
   the fixture) until the suite is green, add a `changes/` fragment describing
   the parity change, and open a PR. CI re-runs the parity gate on the PR.

The set of release-blocking parity fields is defined by Story 4.3's cross-SDK
diagnostic contract (currently `reason`, `environment`, `bucket_value`,
`variation_key`, and the hashed `visitor` reference).

## Dependency bounds (qs-09)

`httpx` is the SDK's **only** runtime dependency (the bucketing layer ships a
pure-Python MurmurHash3 — there is no hashing dependency). `pyproject.toml`
declares a compatible-release **range** (`httpx>=0.28,<1.0`); exact lower-bound
pins live **only** in `ci/lower-bounds-overrides.txt`.

CI verifies both edges of the declared range in the `bounds-check` job:

- **Lower bound** — installs `httpx==0.28.0` (from the override file) on Python
  3.9 and runs the unit + integration suite. This is where age-related breakage
  surfaces first.
- **Upper bound** — resolves the newest compatible versions on Python 3.13 and
  runs the same suite.

**Widening bounds is a deliberate maintainer action**, evaluated at release time
(not opportunistically): confirm the upstream changelog, update the range in
`pyproject.toml` and the pin in `ci/lower-bounds-overrides.txt`, add a `changes/`
fragment, and let the bounds-check job validate both edges.

## Changelog (qs-10)

The changelog is compiled by [towncrier](https://towncrier.readthedocs.io/) from
news fragments under `changes/`. **Never hand-edit `CHANGELOG.md`.**

- Every PR with user-visible impact adds a fragment named
  `{pr_or_issue}.{category}.md` (categories: `feature`, `bugfix`, `breaking`,
  `deprecation`, `internal`). See `changes/README.md`.
- CI fails a package-touching PR that has no fragment (`towncrier check`).
- Fragments are compiled into `CHANGELOG.md` **only at release time**, by the
  release workflow — compiling on a feature branch causes changelog merge
  conflicts.

Preview the unreleased changelog without consuming fragments:

```bash
uv run towncrier build --draft --version X.Y.Z
```

## Cutting a release

1. **Bump the version.** Edit `src/convert_sdk/version.py`:

   ```python
   __version__ = "0.1.0"
   ```

2. **Validate locally.**

   ```bash
   python scripts/verify_release.py --version 0.1.0
   ```

3. **Open the version-bump PR**, get CI green, and merge to `main`.

4. **Tag and push.** Tag the merge commit and push the tag (this is the only
   trigger for the release workflow):

   ```bash
   git checkout main && git pull
   git tag v0.1.0
   git push origin v0.1.0
   ```

   Prerelease tags (`v0.1.0rc1`, `v0.1.0b1`, `v0.1.0a1`, `…dev1`) are supported;
   they publish to PyPI and are marked as prereleases on the GitHub Release.

5. **The release workflow** (`.github/workflows/release.yml`) then:
   - reuses `ci.yml` as the full gate,
   - verifies the tag matches `__version__`,
   - compiles the towncrier changelog (`towncrier build --yes`),
   - builds the wheel + sdist (`uv build`),
   - publishes to PyPI via OIDC Trusted Publishing,
   - creates a GitHub Release using the compiled changelog section
     (`scripts/extract_release_notes.py`).

## PyPI Trusted Publisher — one-time setup (manual, qs-11)

PyPI publishing uses **OIDC Trusted Publishing**. There are **no long-lived PyPI
tokens** in repository secrets. Before the first release, a maintainer configures
the Trusted Publisher on pypi.org (this is a one-time human action; it cannot be
automated from CI):

1. Sign in to <https://pypi.org> as an owner of the `convert-python-sdk` project
   (or, for the first publish, configure a *pending* publisher).
2. Go to the project's **Settings → Publishing → Add a new publisher** (GitHub
   Actions).
3. Enter:
   - **Owner / repository:** `convertcom/python-sdk`
   - **Workflow filename:** `release.yml`
   - **Environment name:** `pypi`
4. Save. The `publish-pypi` job's `environment: pypi` and `id-token: write`
   permission then satisfy the OIDC exchange on the next `v*` tag.

If the publisher is misconfigured, the publish step fails with an OIDC auth
error — re-check the owner/repo/workflow/environment values above.

## Verifying the workflow on a fork (manual, qs-11)

To validate the release pipeline's structure without a real PyPI publish, push a
test tag (e.g. `v0.0.1-test`) to a fork. The workflow runs the full CI gate,
builds, and reaches the publish step; without a Trusted Publisher configured on
the fork it fails at the OIDC exchange, which is the expected and acceptable
outcome for a structure check. This is a maintainer verification step performed
manually, not part of the automated pipeline.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `tag (X) does not match package version (Y)` | Forgot to bump `version.py` | Bump `__version__`, re-tag |
| OIDC auth error on publish | Trusted Publisher not configured | Configure it on pypi.org (above) |
| `towncrier check` fails on a PR | Missing `changes/` fragment | Add a `{pr}.{category}.md` fragment |
| Coverage gate fails | New code without tests / evaluation < 95% | Add tests; never lower the floor |
| bounds-check (lower) fails | Code relies on a newer `httpx` than 0.28.0 | Fix the code or widen the lower bound deliberately |
| Parity gate fails | JS contract drift on a critical field | Fix the Python implementation, not the fixture |
