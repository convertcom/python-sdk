# Python SDK Releases

The Convert Python SDK follows
[Semantic Versioning](https://semver.org/). Releases are tag-driven and
publish to PyPI through Trusted Publishing (OIDC, no long-lived
tokens).

- **Package on PyPI:** https://pypi.org/project/convert-python-sdk/
- **Source repository:** https://github.com/convertcom/python-sdk
- **GitHub releases:** https://github.com/convertcom/python-sdk/releases

## Release notes

Every release publishes notes to the GitHub Releases page. Notes are
compiled from `changes/` fragments by `towncrier` at tag time and
copied into [`CHANGELOG.md`](https://github.com/convertcom/python-sdk/blob/main/CHANGELOG.md).

## Versioning

The SDK follows [Semantic Versioning](https://semver.org/):

| Bump  | When                                                                       |
| ----- | -------------------------------------------------------------------------- |
| MAJOR | Backwards-incompatible public API changes (rare while in `0.x`).           |
| MINOR | Additive backwards-compatible features.                                    |
| PATCH | Backwards-compatible bug fixes.                                            |

While the SDK is in `0.x`, treat **minor** bumps as the breaking-change
boundary; pin to a minor range in production:

```bash
pip install "convert-python-sdk>=0.1,<0.2"
```

## Pre-releases

Release candidates ship as `vX.Y.ZrcN` tags and publish to PyPI as
`X.Y.ZrcN`. Install one explicitly:

```bash
pip install "convert-python-sdk==0.2.0rc1"
```

Pre-releases are not picked up by default by `pip install`; use them
when you want to validate an upcoming minor in staging before it goes
GA.

## Checking the installed version

```python
import convert_sdk

print(convert_sdk.__version__)
```

Or from the shell:

```bash
python -c "import convert_sdk; print(convert_sdk.__version__)"
```

## Reporting a regression

When opening an issue on the
[GitHub repository](https://github.com/convertcom/python-sdk/issues),
include:

1. The output of `python -c "import convert_sdk; print(convert_sdk.__version__)"`.
2. The Python version (`python --version`).
3. A minimal reproduction (an SDK init + the failing call).
4. The full traceback.
5. Any `convert_sdk.diagnostics` log output if you can capture it.

## Next steps

- [Python Quickstart](python-quickstart.md) — install and run
- [Initialization](python-initialization.md) — SDK lifecycle
- [Configuration Options](python-configuration.md) — every config field
