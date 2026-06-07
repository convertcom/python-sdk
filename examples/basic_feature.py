"""Basic feature-resolution example: read typed feature variables.

Run it::

    python examples/basic_feature.py

Initializes from direct config (offline), creates a visitor context, and resolves
a feature. ``run_feature`` returns a typed ``FeatureResult`` with type-cast
variables when the visitor buckets into a variation that enables the feature, or
``None`` for a normal miss (undeclared / unavailable / disabled feature). It never
raises for normal outcomes.

Framework-agnostic: plain Python, no web framework required.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from convert_sdk import Core, SDKConfig

from examples._sample_config import SAMPLE_CONFIG


def run(visitor_id: str = "visitor-001") -> Optional[Dict[str, Any]]:
    """Resolve the sample feature for ``visitor_id``.

    Returns a summary dict with the feature status and type-cast variables, or
    ``None`` for a normal miss.
    """
    core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
    context = core.create_context(visitor_id)

    feature = context.run_feature("checkout-banner")
    core.close()

    if feature is None:
        return None
    return {
        "feature_key": feature.feature_key,
        "status": feature.status.value,
        "variables": dict(feature.variables),
    }


if __name__ == "__main__":
    summary = run()
    if summary is None:
        print("Feature not enabled for this visitor (normal miss).")
    else:
        print("Feature:", summary["feature_key"])
        print("Status:", summary["status"])
        print("Variables:", summary["variables"])
        # Variables are typed: bool / str / int per the feature definition.
        print("'enabled' is a bool:", isinstance(summary["variables"]["enabled"], bool))
