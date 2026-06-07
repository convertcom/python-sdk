"""Conversion tracking package for the Convert Python SDK (Story 2.1).

This package holds the tracking-domain slice. Story 2.1 introduces ONLY the
first layer — :mod:`convert_sdk.tracking.conversions`, which creates an
in-process conversion event from the immutable snapshot and visitor state
(single responsibility: conversion event creation).

Deliberate scope-narrowing (audit finding F-055): the architecture tree lists
``tracker.py`` as the primary tracking module, but Story 2.1 ships
``conversions.py`` instead and defers ``tracker.py`` orchestration plus
``queue.py`` / ``deduplication.py`` / ``payloads.py`` / ``flush.py`` to later
Epic 2 stories. Nothing here performs network I/O, payload serialization,
batching, deduplication, or flush control.
"""

from convert_sdk.tracking.conversions import create_conversion

__all__ = ["create_conversion"]
