"""K13-C AI integration bridge.

This package is a bridge-only abstraction layer. It does not call external AI
providers, read secrets, register runtime routes, or integrate with K12.
"""

from .ai_bridge import (
    BRIDGE_MODE,
    C14_INTEGRATION,
    K13_C_MODE,
    K13_RUNTIME,
    AIAnalysisBridge,
)

__all__ = [
    "AIAnalysisBridge",
    "BRIDGE_MODE",
    "K13_C_MODE",
    "K13_RUNTIME",
    "C14_INTEGRATION",
]
