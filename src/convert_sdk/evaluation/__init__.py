"""Internal evaluation package for local experience decisions (Story 1.4).

This package owns deterministic bucketing (:mod:`bucketing`), audience/location
rule qualification (:mod:`rules`), and snapshot-backed experience selection
(:mod:`experiences`). It is internal — nothing here is re-exported on the public
``convert_sdk`` namespace. Evaluation logic is local to the immutable
:class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`; it performs no
network I/O, no config refresh, and no tracking/persistence side effects.
"""
