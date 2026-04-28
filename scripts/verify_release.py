"""Pre-release checks a maintainer can run locally before tagging.

This script is the maintainer-facing companion to the release CI pipeline:
running it at HEAD reproduces the full set of release gates without pushing
a tag. It exits non-zero on the first failure and prints the failing command.

Usage:
    uv run python scripts/verify_release.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


GATES: list[tuple[str, list[str]]] = [
    ("Ruff lint", ["uv", "run", "ruff", "check", "."]),
    ("mypy strict", ["uv", "run", "mypy"]),
    (
        "pytest with overall coverage gate",
        [
            "uv",
            "run",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--cov=convert_sdk",
            "--cov-report=term-missing",
            "--cov-fail-under=85",
        ],
    ),
    (
        "evaluation/ coverage gate (>=95%)",
        [
            "uv",
            "run",
            "coverage",
            "report",
            "--include=src/convert_sdk/evaluation/*",
            "--fail-under=95",
        ],
    ),
    (
        "parity gate (cross-SDK fixtures)",
        ["uv", "run", "pytest", "tests/parity", "-x", "--tb=short", "-p", "no:cacheprovider"],
    ),
    ("uv build", ["uv", "build"]),
]


def main() -> int:
    if shutil.which("uv") is None:
        print("error: `uv` is required on PATH for the release-verify script.", file=sys.stderr)
        return 2

    for label, command in GATES:
        print(f"==> {label}")
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"FAIL: {label} (command: {' '.join(command)})", file=sys.stderr)
            return result.returncode

    print("\nAll release gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
