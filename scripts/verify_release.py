#!/usr/bin/env python3
"""Run every release gate locally, mirroring CI (Story 5.1, qs-02/03/09/11).

This is the maintainer's single green-bar command: it reproduces the gates that
`.github/workflows/ci.yml` enforces, so a release candidate can be validated on
a workstation before a `v*` tag is pushed. Each gate runs in sequence; the
script reports a per-gate PASS/FAIL summary and exits non-zero if ANY gate fails.

Gates, in order:
    1. Ruff lint          (E/W/F/B/SIM/RUF on src + tests + scripts)
    2. mypy --strict      (the shippable package)
    3. pytest + coverage  (full suite; project floor 85%)
    4. evaluation/ floor  (evaluation modules >= 95%)
    5. parity suite       (tests/parity/ must pass 100% — release-blocking)
    6. towncrier draft    (fragments compile into a valid changelog draft)
    7. uv build           (wheel + sdist build cleanly)

Usage:
    python scripts/verify_release.py
    python scripts/verify_release.py --version 0.1.0   # towncrier draft version
    python scripts/verify_release.py --skip-build      # skip the slow uv build

Exit codes:
    0  all gates passed
    1  one or more gates failed
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_COVERAGE_FLOOR = 95


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Runner:
    """Sequences gates and accumulates results."""

    results: list[GateResult] = field(default_factory=list)

    def run(self, name: str, cmd: list[str]) -> bool:
        print(f"\n=== {name} ===\n$ {' '.join(cmd)}", flush=True)
        completed = subprocess.run(cmd, cwd=REPO_ROOT)
        passed = completed.returncode == 0
        self.results.append(
            GateResult(name, passed, "" if passed else f"exit {completed.returncode}")
        )
        return passed


def _coverage_gate(runner: Runner) -> None:
    """Run the full suite under coverage (project floor enforced by --cov-fail-under)."""
    runner.run(
        "pytest + coverage (project floor 85%)",
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--cov=convert_sdk",
            "--cov-report=term-missing",
            "--cov-fail-under=85",
        ],
    )


def _evaluation_coverage_gate(runner: Runner) -> None:
    """Enforce the evaluation/ 95% floor against the coverage data just collected."""
    print(
        f"\n=== evaluation/ coverage (floor {EVALUATION_COVERAGE_FLOOR}%) ===",
        flush=True,
    )
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "report",
        "--include=*/convert_sdk/evaluation/*",
        f"--fail-under={EVALUATION_COVERAGE_FLOOR}",
    ]
    print(f"$ {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=REPO_ROOT)
    passed = completed.returncode == 0
    runner.results.append(
        GateResult(
            f"evaluation/ coverage >= {EVALUATION_COVERAGE_FLOOR}%",
            passed,
            "" if passed else f"exit {completed.returncode}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default="0.0.0",
        help="Version passed to the towncrier draft build (default: 0.0.0).",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip the (slow) uv build gate.",
    )
    args = parser.parse_args(argv)

    runner = Runner()

    runner.run("Ruff lint", ["ruff", "check", "src", "tests", "scripts"])
    runner.run("mypy --strict", ["mypy", "--strict"])
    _coverage_gate(runner)
    _evaluation_coverage_gate(runner)
    runner.run(
        "parity suite (release-blocking)",
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "tests/parity", "-x"],
    )
    runner.run(
        "towncrier draft",
        ["towncrier", "build", "--draft", "--version", args.version],
    )
    if not args.skip_build:
        runner.run("uv build (wheel + sdist)", ["uv", "build"])

    print("\n" + "=" * 60)
    print("Release gate summary")
    print("=" * 60)
    all_passed = True
    for result in runner.results:
        status = "PASS" if result.passed else "FAIL"
        suffix = f"  ({result.detail})" if result.detail else ""
        print(f"  [{status}] {result.name}{suffix}")
        all_passed = all_passed and result.passed

    if all_passed:
        print("\nAll release gates passed.")
        return 0
    print("\nOne or more release gates FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
