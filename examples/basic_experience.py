"""Runnable Story 1.6 experience evaluation example."""

from __future__ import annotations

from convert_sdk import Core, SDKConfig

from _sample_config import sample_config


def main() -> None:
    core = Core(
        SDKConfig(
            config_data=sample_config(),
            environment="production",
        )
    )
    context = core.create_context("visitor-123", {"tier": "premium"})
    result = context.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    if result is None:
        print("No experience result")
        return

    print("Experience:", result.experience_key)
    print("Variation:", result.variation_key)


if __name__ == "__main__":
    main()
