"""Mock provider adapter for K13-C.

This wraps the completed K13-B deterministic mock engine and keeps K13-C free
of scoring, suggestion, and risk-analysis business logic.
"""

from __future__ import annotations

from backend.app.modules.k.k13_ai_analysis.engine import (
    K13AIEngine,
    K13AnalysisResult,
    ProductPayload,
)

from .provider_interface import AIProvider


class MockProvider(AIProvider):
    """Bridge provider backed by the local-only K13-B mock engine."""

    def analyze(self, product: ProductPayload) -> K13AnalysisResult:
        return K13AIEngine.analyze(product)
