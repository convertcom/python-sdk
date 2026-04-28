"""Extract the section for a given version from CHANGELOG.md.

Used by `.github/workflows/release.yml` to feed `gh release create --notes-file`
with just the notes for the version being published. The workflow runs
`towncrier build --version <X>` immediately before this script, so the
section is already present in CHANGELOG.md when we read it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HEADING_PATTERN = re.compile(r"^##\s+\[?([^\]\s]+)\]?", re.MULTILINE)


def extract_section(changelog_text: str, version: str) -> str:
    matches = list(HEADING_PATTERN.finditer(changelog_text))
    for index, match in enumerate(matches):
        if match.group(1) == version:
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(changelog_text)
            return changelog_text[start:end].strip() + "\n"
    raise SystemExit(f"No CHANGELOG.md section found for version {version!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Version string without the leading 'v'")
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="Path to CHANGELOG.md (default: CHANGELOG.md at repo root)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output file ('-' for stdout, default '-')",
    )
    args = parser.parse_args(argv)

    changelog_path = Path(args.changelog)
    if not changelog_path.is_file():
        raise SystemExit(f"Changelog not found: {changelog_path}")

    section = extract_section(changelog_path.read_text(encoding="utf-8"), args.version)

    if args.output == "-":
        sys.stdout.write(section)
    else:
        Path(args.output).write_text(section, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
