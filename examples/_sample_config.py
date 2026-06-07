"""Shared sample config for the runnable examples.

A small but realistic *direct* config payload so the examples run locally with
no network access and no external services. It exercises both surfaces of the
SDK:

* an unrestricted experiment (``checkout-experiment``) with two variations, so
  ``run_experience`` returns a typed result for any visitor; and
* a declared feature (``checkout-banner``) whose variation changes carry typed
  ``fullStackFeature`` data, so ``run_feature`` returns a typed, type-cast
  result.

All identifiers are placeholders. There are no secrets here — the networked
``sdk_key`` flow in ``direct_config.py`` reads its key from an environment
variable instead of hard-coding one.
"""

from __future__ import annotations

from typing import Any, Dict

#: A self-contained config payload suitable for ``SDKConfig(data=...)``.
SAMPLE_CONFIG: Dict[str, Any] = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "features": [
        {
            "id": "10024",
            "key": "checkout-banner",
            "name": "Checkout Banner",
            "variables": [
                {"key": "enabled", "type": "boolean"},
                {"key": "headline", "type": "string"},
                {"key": "max_items", "type": "integer"},
            ],
        }
    ],
    "experiences": [
        {
            "id": "e1",
            "key": "checkout-experiment",
            "variations": [
                {
                    "id": "v1",
                    "key": "control",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c1",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "false",
                                    "headline": "Standard checkout",
                                    "max_items": "3",
                                },
                            },
                        }
                    ],
                },
                {
                    "id": "v2",
                    "key": "treatment",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c2",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "true",
                                    "headline": "Free shipping over $50!",
                                    "max_items": "5",
                                },
                            },
                        }
                    ],
                },
            ],
        }
    ],
}
