"""Runnable Story 1.6 direct-config initialization example."""

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
    print("SDK ready:", core.is_ready)
    print("Context visitor:", context.visitor_id)


if __name__ == "__main__":
    main()
