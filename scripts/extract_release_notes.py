#!/usr/bin/env python3
"""Extract a single version's section from CHANGELOG.md (Story 5.1, qs-11).

The release workflow (`.github/workflows/release.yml`) compiles the towncrier
fragments into `CHANGELOG.md`, then calls this script to pull out just the
section for the version being released so it can feed `gh release create
--notes-file`. This keeps the GitHub Release body byte-identical to the
changelog section for that version.

Section detection matches the towncrier `title_format` configured in
`pyproject.toml`: a level-2 heading whose text starts with the version, e.g.

    ## 0.1.0 (2026-06-08)

The extracted notes are everything between that heading and the next level-2
heading (or end of file), with surrounding blank lines trimmed.

Usage:
    python scripts/extract_release_notes.py --version 0.1.0
    python scripts/extract_release_notes.py --version 0.1.0 --changelog CHANGELOG.md
    python scripts/extract_release_notes.py --version 0.1.0 --output notes.md

Exit codes:
    0  notes extracted (written to --output or stdout)
    1  version section not found / changelog missing
    2  bad arguments
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _normalize_version(version: str) -> str:
    """Strip a leading ``v`` so ``v0.1.0`` and ``0.1.0`` both match."""
    return version[1:] if version.startswith("v") else version


def extract_release_notes(changelog: str, version: str) -> str | None:
    """Return the changelog body for ``version``, or ``None`` if not present.

    Matches a level-2 heading whose text begins with the (normalized) version
    token, tolerating an optional trailing ``(date)`` suffix. The returned body
    excludes the heading line itself and is stripped of leading/trailing blank
    lines.
    """
    target = _normalize_version(version)
    lines = changelog.splitlines()

    # A level-2 heading introducing a version section. The version token must be
    # delimited (whitespace or end) so "0.1.0" does not match "0.1.01".
    heading_re = re.compile(r"^##\s+(?P<ver>\S+)")

    start: int | None = None
    for index, line in enumerate(lines):
        match = heading_re.match(line)
        if match and _normalize_version(match.group("ver")) == target:
            start = index + 1
            break

    if start is None:
        return None

    body: list[str] = []
    for line in lines[start:]:
        if heading_re.match(line):
            break
        body.append(line)

    return "\n".join(body).strip("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        required=True,
        help="Version to extract (with or without a leading 'v').",
    )
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="Path to the changelog file (default: CHANGELOG.md).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write the notes to this file instead of stdout.",
    )
    args = parser.parse_args(argv)

    changelog_path = Path(args.changelog)
    if not changelog_path.is_file():
        print(f"error: changelog not found: {changelog_path}", file=sys.stderr)
        return 1

    notes = extract_release_notes(
        changelog_path.read_text(encoding="utf-8"), args.version
    )
    if notes is None:
        print(
            f"error: no section for version {args.version!r} in {changelog_path}",
            file=sys.stderr,
        )
        return 1

    if args.output:
        Path(args.output).write_text(notes + "\n", encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
