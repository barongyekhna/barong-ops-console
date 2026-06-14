"""Provider contract for the K13-C AI bridge."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.modules.k.k13_ai_analysis.engine import (
    K13AnalysisResult,
    ProductPayload,
)


class AIProvider(ABC):
    """Uniform provider interface for mock and future live AI analysis."""

    @abstractmethod
    def analyze(self, product: ProductPayload) -> K13AnalysisResult:
        """Analyze a product payload and return the normalized K13 result."""
        raise NotImplementedError
