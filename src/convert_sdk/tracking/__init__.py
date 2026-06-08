"""Conversion tracking package for the Convert Python SDK (Stories 2.1 + 2.2).

This package holds the tracking-domain slice. Story 2.1 introduced the first
layer — :mod:`convert_sdk.tracking.conversions`, which creates an in-process
conversion event from the immutable snapshot and visitor state (single
responsibility: conversion event creation).

Story 2.2 adds the second layer — :mod:`convert_sdk.tracking.payloads`, the
single place that maps internal snake_case conversion events to the verbose
JS-SDK outbound wire contract (``build_tracking_payload``).

Deliberate scope-narrowing (audit finding F-055): the architecture tree lists
``tracker.py`` as the primary tracking module, but Stories 2.1/2.2 ship
``conversions.py`` and ``payloads.py`` and defer ``tracker.py`` orchestration
plus ``queue.py`` / ``deduplication.py`` / ``flush.py`` to later Epic 2 stories.
Nothing here performs network I/O, batching, deduplication, or flush control.
"""

from convert_sdk.tracking.conversions import create_conversion
from convert_sdk.tracking.deduplication import DedupDecision, evaluate_dedup
from convert_sdk.tracking.flush import (
    flush,
    register_atexit_flush,
    setup_periodic_flush,
)
from convert_sdk.tracking.payloads import TRACKING_SOURCE, build_tracking_payload
from convert_sdk.tracking.queue import ReleaseReason, TrackingQueue
from convert_sdk.tracking.tracker import Tracker

__all__ = [  # noqa: RUF022 - grouped by story for readability, not alphabetized
    "create_conversion",
    "build_tracking_payload",
    "TRACKING_SOURCE",
    # Story 2.3 tracking internals.
    "TrackingQueue",
    "ReleaseReason",
    "DedupDecision",
    "evaluate_dedup",
    "Tracker",
    "flush",
    "setup_periodic_flush",
    "register_atexit_flush",
]
