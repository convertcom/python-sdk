from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_example(script_name: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "examples" / script_name)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_direct_config_example_runs() -> None:
    output = run_example("direct_config.py")
    assert "SDK ready: True" in output
    assert "Context visitor: visitor-123" in output


def test_basic_experience_example_runs() -> None:
    output = run_example("basic_experience.py")
    assert "Experience: checkout-flow" in output
    assert "Variation:" in output


def test_basic_feature_example_runs() -> None:
    output = run_example("basic_feature.py")
    assert "Feature: checkout-banner" in output
    assert "Status: enabled" in output
