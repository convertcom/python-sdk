# JavaScript Parity Fixtures

This directory holds checked-in parity fixtures for behavior that should stay aligned with the sibling JavaScript SDK.

## Source of Truth

- Reference repo: `../javascript-sdk`
- Reference package: `../javascript-sdk/packages/js-sdk`
- Reference config: `../javascript-sdk/packages/js-sdk/tests/test-config.json`

## Regeneration

From the Python SDK repo root, regenerate fixtures with:

```bash
uv run python scripts/generate_parity_fixtures.py
```

The script reads representative scenarios from the sibling JavaScript SDK, normalizes the outcomes, and writes JSON fixtures into `tests/parity/fixtures/`.

Normal `pytest` runs only read the checked-in fixtures. They do not require Node or the JavaScript repo at runtime.
