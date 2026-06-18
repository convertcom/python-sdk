/*
 * release.config.mjs — semantic-release configuration for the Convert Python SDK.
 *
 * Triggered by `.github/workflows/release.yml` on every successful "CI" run on
 * `main` (via `workflow_run`). Analyzes the conventional commits since the last
 * tag, decides the next version, writes that version into
 * `src/convert_sdk/version.py` (build-time, NOT committed), builds the
 * wheel + sdist, publishes to PyPI via OIDC Trusted Publishing, then creates
 * the `vX.Y.Z` tag + a GitHub Release carrying the generated notes.
 *
 * IMPORTANT: this release NEVER pushes a commit to `main`. semantic-release
 * core pushes only the *tag* (a `refs/tags/*` ref — not gated by the branch
 * ruleset) and `@semantic-release/github` creates the Release via the API. The
 * version write in `src/convert_sdk/version.py` is a build-time, working-tree
 * write consumed by `uv build` (hatchling reads `__version__` via
 * `[tool.hatch.version] path`) and intentionally NOT committed; the NEXT release
 * derives its version from this run's git tag.
 *
 * Plugin order is LOAD-BEARING:
 *
 * (four plugins; `exec` carries BOTH commands in a single entry):
 *
 *   1. commit-analyzer          → decide next version from feat/fix/BREAKING
 *   2. release-notes-generator  → render markdown release notes
 *   3. exec                     → verifyReleaseCmd: export version + notes to job
 *                                  outputs (runs in dry-run AND real run; harmless
 *                                  in real run).
 *                                  prepareCmd: write nextRelease.version into
 *                                  version.py (real run only; dry-run skips prepare).
 *   4. github                   → create vX.Y.Z tag + GitHub Release (via API)
 *
 * Publish-before-Release: the `publish-pypi` job (pypa/gh-action-pypi-publish)
 * runs between `prepare` and `release` in the workflow. The `release` job
 * (`needs: [prepare, publish-pypi]`) ensures the GitHub Release/tag is only
 * created AFTER a successful PyPI upload.
 *
 * FORBIDDEN here (ratified house lessons — Android qs-03/qs-04): no
 * @semantic-release/git (nothing commits to main), no @semantic-release/changelog
 * (no committed CHANGELOG — the changelog lives on GitHub Releases).
 */

export default {
  // Only publish from `main`. `yarn release:dry-run` previews on any branch,
  // but `yarn release` refuses to publish from anything else.
  branches: ['main'],

  // All git tags use the `v` prefix (v1.0.0, v1.2.3). Matches the PHP/Android/
  // Ruby SDKs.
  tagFormat: 'v${version}',

  plugins: [
    // 1. Map conventional commits to SemVer impact.
    //    feat: X            → minor bump
    //    fix: X             → patch bump
    //    BREAKING CHANGE: … → major bump
    //    Anything else (chore/docs/ci/test/style/perf/refactor) → no release.
    [
      '@semantic-release/commit-analyzer',
      {
        preset: 'conventionalcommits',
      },
    ],

    // 2. Build the markdown release notes. Mirrors the PHP/Android/Ruby types
    //    map — only feat/fix/refactor are surfaced to users; maintenance commit
    //    types (chore/docs/ci/test/style/perf) are hidden.
    [
      '@semantic-release/release-notes-generator',
      {
        preset: 'conventionalcommits',
        presetConfig: {
          types: [
            { type: 'feat', section: 'Features' },
            { type: 'fix', section: 'Bug Fixes' },
            { type: 'refactor', section: 'Refactoring' },
            { type: 'chore', hidden: true },
            { type: 'docs', hidden: true },
            { type: 'ci', hidden: true },
            { type: 'test', hidden: true },
            { type: 'style', hidden: true },
            { type: 'perf', hidden: true },
          ],
        },
      },
    ],

    // 3. Export the computed version + notes to the prepare job's outputs and
    //    write the notes to a file. Runs in BOTH the dry-run (prepare job) and
    //    the real run (release job) — harmless in the real run because
    //    GITHUB_OUTPUT is always set in Actions.
    //
    //    verifyReleaseCmd runs in the verifyRelease lifecycle phase (included in
    //    --dry-run). prepareCmd runs in the prepare phase (skipped by --dry-run).
    [
      '@semantic-release/exec',
      {
        verifyReleaseCmd:
          'if [ -n "$GITHUB_OUTPUT" ]; then { echo "released=true"; echo "version=${nextRelease.version}"; } >> "$GITHUB_OUTPUT"; fi; if [ -n "$RELEASE_NOTES_FILE" ]; then printf \'%s\' "${nextRelease.notes}" > "$RELEASE_NOTES_FILE"; fi',
        // Stamp the version into version.py. Uses `node -e` (not python) so it
        // depends ONLY on Node, which BOTH the prepare and release jobs install
        // via setup-node. (The release job has no uv/python setup; relying on
        // the runner's system `python` symlink would risk an orphaned PyPI
        // release if the stamp failed after publish. Mirrors ruby-sdk, whose
        // prepareCmd uses `ruby -e` — the runtime already present in its jobs.)
        prepareCmd:
          'node -e \'const fs=require("fs");const f="src/convert_sdk/version.py";fs.writeFileSync(f,fs.readFileSync(f,"utf8").replace(/__version__ = "[^"]*"/,`__version__ = "${nextRelease.version}"`))\'',
      },
    ],

    // 4. Create the `vX.Y.Z` tag + a GitHub Release with the generated notes.
    //    semantic-release core pushes the tag (a `refs/tags/*` ref — NOT gated
    //    by the `main` branch ruleset); this plugin creates the Release via the
    //    GitHub API. There is NO commit-back to `main`.
    [
      '@semantic-release/github',
      {
        // release.yml grants `contents: write` only on the release job;
        // the plugin's default PR/issue success comments AND `releasedLabels`
        // write to issues/PRs (need issues:write + pull-requests:write) and
        // would 403. Disable them all — the Release + tag (contents:write) are
        // all we need. (Android qs-03 / TD-2.)
        successComment: false,
        failComment: false,
        failTitle: false,
        releasedLabels: false,
      },
    ],
  ],
};
