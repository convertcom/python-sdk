"""Basic experiment example: bucket a visitor into a variation.

Run it::

    python examples/basic_experience.py

Initializes from direct config (offline), creates a visitor-scoped context, and
evaluates an experience. ``run_experience`` returns a typed ``ExperienceResult``
when the visitor qualifies and buckets into a variation, or ``None`` for a normal
miss — it never raises for normal outcomes.

Framework-agnostic: plain Python, no web framework required.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from convert_sdk import Core, SDKConfig

from examples._sample_config import SAMPLE_CONFIG


def run(visitor_id: str = "visitor-001") -> Optional[Dict[str, Any]]:
    """Evaluate the sample experiment for ``visitor_id``.

    Returns a small summary dict for the bucketed variation, or ``None`` for a
    normal miss.
    """
    core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
    context = core.create_context(visitor_id)

    result = context.run_experience("checkout-experiment")
    core.close()

    if result is None:
        return None
    return {
        "experience_key": result.experience_key,
        "variation_key": result.variation_key,
        "variation_id": result.variation_id,
    }


if __name__ == "__main__":
    summary = run()
    if summary is None:
        print("Visitor did not bucket into a variation (normal miss).")
    else:
        print("Experience:", summary["experience_key"])
        print("Bucketed variation:", summary["variation_key"])
