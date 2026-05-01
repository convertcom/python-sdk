# Site pages — `docs.developers.convert.com`

This directory holds the per-SDK Python pages intended for publishing on
[`docs.developers.convert.com`](https://docs.developers.convert.com/),
laid out to match the slug structure used by the JavaScript and PHP
Full Stack SDKs.

The topic guides under [`docs/`](../) (e.g. `evaluation.md`,
`tracking.md`, `extending.md`) remain the in-repo reference. The pages
here are intentionally smaller, follow the JS/PHP page contract one-to-one,
and are the canonical source for what gets published.

## Page → slug mapping

| File                                | Published slug                  | JS counterpart           | PHP counterpart        |
| ----------------------------------- | ------------------------------- | ------------------------ | ---------------------- |
| `python-quickstart.md`              | `/docs/python-quickstart`       | `javascript-quickstart`  | `php-quickstart`       |
| `python-installation.md`            | `/docs/python-installation`     | `javascript-installation`| `php-installation`     |
| `python-initialization.md`          | `/docs/python-initialization`   | `javascript-initialization` | `php-initialization` |
| `python-configuration.md`           | `/docs/python-configuration`    | `javascript-configuration` | `php-configuration` |
| `python-code-examples.md`           | `/docs/python-code-examples`    | `javascript-code-examples` | `php-code-examples` |
| `python-return-types.md`            | `/docs/python-return-types`     | `javascript-types`       | `php-return-types`     |
| `python-segments-manager.md`        | `/docs/python-segments-manager` | (shared concept page)    | `php-segments-manager` |
| `releases-python-sdk.md`            | `/docs/releases-python-sdk`     | `releases-js-sdk`        | (none)                 |

## Cross-references

Internal links between pages use bare filenames (`python-installation.md`,
not absolute URLs) so they can be rewritten by the docs publishing
pipeline without source-side churn.

Cross-references to **shared Full Stack pages** that already exist on
`docs.developers.convert.com` (e.g. `how-convert-works`,
`running-experiences`, `tracking-conversions`) use the same bare slug —
those pages are not republished as Python-specific copies.

## Maintenance

When you change SDK behaviour, update both:

1. The relevant page in this `site/` directory (publishable surface).
2. The matching topic guide in [`docs/`](../) (in-repo reference).

The two are kept consistent on purpose: the topic guides go deeper
(architecture rationale, edge cases, runtime caveats); the site pages
match the JS/PHP page contract that already exists on the docs portal.
