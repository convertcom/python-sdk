# Changelog Fragments

`towncrier` compiles fragments from this directory into `CHANGELOG.md` at
release time. Every PR that changes user-visible behavior must include a
fragment; the `Changelog fragment present` CI check fails the PR otherwise.

## Naming

`changes/<issue_or_pr>.<category>.md`

Categories:

| Category      | When to use                                                      |
| ------------- | ---------------------------------------------------------------- |
| `feature`     | New public API or capability.                                    |
| `bugfix`      | Behavioral fix for shipped functionality.                        |
| `breaking`    | Incompatible API/behavior change. Triggers a major-version bump. |
| `deprecation` | Public surface marked for removal in a later release.            |
| `internal`    | Maintenance with no user-visible effect (CI, refactor, deps).    |

## Format

One short sentence per fragment. Issue/PR cross-references render as links
because of the `issue_format` setting in `pyproject.toml`. Example:

```markdown
Add ``Core.create_context`` shortcut for synchronous bootstrapping.
```

## Removing fragments

Don't. `towncrier build` removes consumed fragments at release time; manual
deletion before that point causes lost release notes.
