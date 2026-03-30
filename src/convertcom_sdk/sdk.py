from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from convertcom_sdk.api import ApiManager
from convertcom_sdk.bucketing import BucketingManager
from convertcom_sdk.config import build_config
from convertcom_sdk.core import Core
from convertcom_sdk.data import DataManager, DataStoreManager
from convertcom_sdk.events import EventManager
from convertcom_sdk.experience import ExperienceManager
from convertcom_sdk.features import FeatureManager
from convertcom_sdk.logger import LogManager
from convertcom_sdk.rules import RuleManager
from convertcom_sdk.segments import SegmentsManager


class ConvertSDK(Core):
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        request_sender: Any | None = None,
    ) -> None:
        configuration = build_config(config)
        logger_config = configuration.get("logger") or {}
        logger_manager = LogManager(level=logger_config.get("logLevel", "debug"))
        for client in logger_config.get("customLoggers") or []:
            if isinstance(client, Mapping):
                logger = client.get("logger")
                if logger is not None:
                    logger_manager.add_client(
                        logger,
                        client.get("logLevel", logger_config.get("logLevel", "debug")),
                        client.get("methodsMap") or client.get("methodMap"),
                    )
            elif client is not None:
                logger_manager.add_client(
                    client,
                    logger_config.get("logLevel", "debug"),
                )
        event_manager = EventManager(configuration, logger_manager=logger_manager)
        api_manager = ApiManager(
            configuration,
            event_manager=event_manager,
            request_sender=request_sender,
        )
        bucketing_manager = BucketingManager(configuration)
        rule_manager = RuleManager(configuration)
        data_store_manager = None
        if configuration.get("dataStore"):
            data_store_manager = DataStoreManager(
                configuration,
                data_store=configuration.get("dataStore"),
                event_manager=event_manager,
                logger_manager=logger_manager,
            )
        data_manager = DataManager(
            configuration,
            bucketing_manager=bucketing_manager,
            rule_manager=rule_manager,
            data_store_manager=data_store_manager,
            api_manager=api_manager,
        )
        experience_manager = ExperienceManager(configuration, data_manager=data_manager)
        feature_manager = FeatureManager(configuration, data_manager=data_manager)
        segments_manager = SegmentsManager(
            configuration,
            data_manager=data_manager,
            rule_manager=rule_manager,
        )
        super().__init__(
            configuration,
            data_manager=data_manager,
            event_manager=event_manager,
            experience_manager=experience_manager,
            feature_manager=feature_manager,
            segments_manager=segments_manager,
            api_manager=api_manager,
        )
