"""Concrete adapters implementing the SDK's ports.

Story 1.2 introduces the httpx-backed transport adapter. Adapters are the only
place external libraries (e.g. ``httpx``) are imported into the SDK's I/O path.
"""
