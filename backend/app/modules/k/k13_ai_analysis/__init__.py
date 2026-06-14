"""K13-B mock AI analysis engine.

This package is deterministic and local-only. It must not call external AI
providers, read secrets, access persistence, or register runtime routes.
"""

from .engine import (
    K13_AI_RUNTIME,
    K13_B_MODE,
    K13_EXTERNAL_API,
    K13AIEngine,
)

__all__ = [
    "K13AIEngine",
    "K13_AI_RUNTIME",
    "K13_B_MODE",
    "K13_EXTERNAL_API",
]
