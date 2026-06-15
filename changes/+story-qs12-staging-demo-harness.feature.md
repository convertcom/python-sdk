Add dual-mode manual-verification demo harness (`demo/`) with OFFLINE default
(committed `config_fixture.json` using real staging entity keys, zero credentials,
deterministic output) and LIVE opt-in (fetches `GET /api/v1/config/{sdkKey}` from
the staging CDN host when `CONVERT_SDK_KEY` is set). Includes an offline RESPX
guard test that deterministically catches the PR #46 class of config-route 404.
Entity keys (`test-experience-ab-fullstack-1`, `test-feature-rollout-1`,
`test-segment-1`, `button-primary-click`, SDK key `10035569/10034190`) are cited
from the JS/PHP reference demos — no invented placeholders (F-066).
