"""Runnable Story 1.6 feature evaluation example."""

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
    result = context.run_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )

    if result is None:
        print("Feature unavailable")
        return

    print("Feature:", result.feature_key)
    print("Status:", result.status.value)
    print("Variables:", dict(result.variables))


if __name__ == "__main__":
    main()
