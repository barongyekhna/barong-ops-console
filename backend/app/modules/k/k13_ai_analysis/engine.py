"""K13-B deterministic mock AI analysis engine.

This module defines the future K12 integration hook as ``analyze(product)``.
It does not execute AI, call providers, read API keys, access persistence, or
register routes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from .risk_engine import analyze_risk
from .scoring_engine import score_product
from .suggestion_engine import generate_suggestions

K13_B_MODE = "mock_engine_only"
K13_AI_RUNTIME = False
K13_EXTERNAL_API = "disabled"

ProductPayload = Mapping[str, Any]


class K13AnalysisResult(TypedDict):
    risk_score: int
    suggestions: list[str]
    warnings: list[str]
    confidence: float
    seo_score: int
    clarity_score: int
    completeness_score: int


def _calculate_confidence(
    risk_score: int,
    seo_score: int,
    clarity_score: int,
    completeness_score: int,
) -> float:
    quality_score = (
        seo_score * 0.25
        + clarity_score * 0.30
        + completeness_score * 0.45
    )
    risk_penalty = risk_score * 0.35
    confidence = (quality_score - risk_penalty) / 100
    return round(max(0.0, min(1.0, confidence)), 2)


class K13AIEngine:
    """Mock-only product analysis engine for future K12 integration."""

    @staticmethod
    def analyze(product: ProductPayload) -> K13AnalysisResult:
        risk_analysis = analyze_risk(product)
        scoring = score_product(product)
        suggestions = generate_suggestions(product, risk_analysis)
        confidence = _calculate_confidence(
            risk_analysis["risk_score"],
            scoring["seo_score"],
            scoring["clarity_score"],
            scoring["completeness_score"],
        )

        return {
            "risk_score": risk_analysis["risk_score"],
            "suggestions": suggestions,
            "warnings": risk_analysis["warnings"],
            "confidence": confidence,
            "seo_score": scoring["seo_score"],
            "clarity_score": scoring["clarity_score"],
            "completeness_score": scoring["completeness_score"],
        }
