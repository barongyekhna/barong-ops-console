"""K13-C bridge-only routing layer for AI analysis.

Data flow boundary for future K12 integration:
K12 product payload -> K13-C bridge -> selected provider -> normalized result.

K13-C does not invoke K12, write state, call external AI providers, read API
keys, or register production/staging runtime behavior.
"""

from __future__ import annotations

from backend.app.modules.k.k13_ai_analysis.engine import (
    K13AnalysisResult,
    ProductPayload,
)

from .live_provider import LiveProvider
from .mock_provider import MockProvider
from .provider_interface import AIProvider

BRIDGE_MODE = "mock"

K13_C_MODE = "bridge_only"
K13_RUNTIME = "disabled_execution"
C14_INTEGRATION = "future_only"


class AIAnalysisBridge:
    """Provider routing entry point for AI analysis."""

    @staticmethod
    def _provider() -> AIProvider:
        if BRIDGE_MODE == "mock":
            return MockProvider()

        if BRIDGE_MODE == "live":
            return LiveProvider()

        raise ValueError(f"Unsupported K13-C bridge mode: {BRIDGE_MODE}")

    @staticmethod
    def analyze(product: ProductPayload) -> K13AnalysisResult:
        return AIAnalysisBridge._provider().analyze(product)
