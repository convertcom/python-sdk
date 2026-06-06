"""Placeholder for the per-visitor context.

Story 1.1 freezes the public import boundary only. The real per-visitor public
API (experience evaluation, feature decisions, conversion tracking) lands in
later stories; this class is an intentional placeholder so later stories can
implement behavior without renaming the public surface.
"""


class Context:
    """Per-visitor context placeholder for the Convert Python SDK.

    This class is deliberately empty in Story 1.1. It exists to freeze the
    ``from convert_sdk import Context`` import boundary.
    """
