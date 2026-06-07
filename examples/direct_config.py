"""Direct-config initialization example.

Run it::

    python examples/direct_config.py

This is the fastest path to a first successful run: the SDK initializes from a
preloaded config payload with **no network call**, so it works offline and in
tests. The same ``Core`` / ``SDKConfig`` surface also supports networked
initialization via an ``sdk_key`` — shown (without making a real request) at the
bottom — where the key is read from an environment variable rather than being
hard-coded.

Framework-agnostic: plain Python, no web framework required.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from convert_sdk import Core, SDKConfig

from examples._sample_config import SAMPLE_CONFIG


def run() -> Dict[str, Any]:
    """Initialize directly from config and report readiness. Returns a summary."""
    # Direct config: no network, ready immediately after initialize().
    core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
    snapshot = core.current_config

    summary: Dict[str, Any] = {
        "ready": core.is_ready,
        "account_id": snapshot.account_id if snapshot else None,
        "experiences": [e.get("key") for e in snapshot.experiences] if snapshot else [],
        "features": [f.get("key") for f in snapshot.features] if snapshot else [],
    }
    core.close()
    return summary


def sdk_key_config_example() -> SDKConfig:
    """Build an ``sdk_key`` config from the environment (no network here).

    Set ``CONVERT_SDK_KEY`` to your key. We only *construct* the config in this
    example to show the secure-injection pattern — we never embed a real key.
    """
    sdk_key = os.environ.get("CONVERT_SDK_KEY", "your-sdk-key-here")
    return SDKConfig(sdk_key=sdk_key)


if __name__ == "__main__":
    result = run()
    print("SDK ready:", result["ready"])
    print("Account:", result["account_id"])
    print("Experiences:", result["experiences"])
    print("Features:", result["features"])
    # Networked init would be: Core(sdk_key_config_example()).initialize()
    print("(sdk_key config built from CONVERT_SDK_KEY env var; no request made)")
