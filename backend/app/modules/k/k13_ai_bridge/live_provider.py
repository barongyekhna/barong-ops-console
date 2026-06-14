"""Future live provider placeholder for C14 activation."""

from __future__ import annotations

from backend.app.modules.k.k13_ai_analysis.engine import (
    K13AnalysisResult,
    ProductPayload,
)

from .provider_interface import AIProvider


class LiveProvider(AIProvider):
    """Disabled live provider boundary.

    Real model provider integration is intentionally outside K13-C and requires
    C14 activation.
    """

    def analyze(self, product: ProductPayload) -> K13AnalysisResult:
        raise NotImplementedError("C14 required for activation")
