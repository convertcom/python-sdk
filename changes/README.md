# Changelog fragments (`changes/`)

The Convert Python SDK uses [towncrier](https://towncrier.readthedocs.io/) to
build `CHANGELOG.md` from per-change news fragments. **Every pull request that
changes user-visible behavior must add a fragment here.** CI fails a PR that
touches the package without a matching fragment (the `changelog-fragment` gate
in `.github/workflows/ci.yml`).

## Adding a fragment

Create a file named `{issue_or_pr_number}.{category}.md` in this directory, for
example `42.feature.md`. The file body is the human-readable changelog line.

```text
changes/42.feature.md
---------------------
Add async evaluation API for FastAPI integrations.
```

## Categories

| Category      | Goes under heading        | Use for                                              |
|---------------|---------------------------|------------------------------------------------------|
| `feature`     | Features                  | New public capabilities                              |
| `bugfix`      | Bug Fixes                 | Fixes to incorrect behavior                          |
| `breaking`    | Breaking Changes          | Backward-incompatible changes (require a major bump) |
| `deprecation` | Deprecations              | APIs scheduled for removal                           |
| `internal`    | Internal / Maintenance    | Tooling, CI, refactors, dependency bumps             |

## Compilation (maintainers only)

Fragments are compiled into `CHANGELOG.md` **only at release time** by the
release workflow — never hand-edit `CHANGELOG.md`, and never run `towncrier
build` on a feature branch (it would create merge conflicts on the changelog).

```bash
# Preview the unreleased changelog without consuming fragments:
uv run towncrier build --draft --version 0.1.0

# Release-time compile (done by .github/workflows/release.yml):
uv run towncrier build --yes --version 0.1.0
```

See `docs/release-process.md` for the full release flow.
