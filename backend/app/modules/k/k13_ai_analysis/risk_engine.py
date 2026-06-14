"""Deterministic mock risk analysis for K13-B.

Allowed input sources are payloads shaped like K06 raw product data, K07 product
form input, or K12 mock review data. This module is pure in-memory logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

ProductPayload = Mapping[str, Any]

EXAGGERATION_KEYWORDS = (
    "best",
    "ultimate",
    "perfect",
    "guaranteed",
    "miracle",
    "unbeatable",
    "world class",
    "number one",
    "#1",
)

UNSAFE_CLAIM_KEYWORDS = (
    "cure",
    "treat",
    "prevent disease",
    "medical grade",
    "sterile",
    "non-toxic",
    "allergy free",
    "child safe",
    "food safe",
)

REQUIRED_FIELD_GROUPS = {
    "title": (
        "title",
        "product_name_en",
        "name",
        "ai_canonical.title",
        "human_edit.title",
    ),
    "description": (
        "description",
        "short_description_en",
        "long_description_en",
        "raw_input_text",
        "raw_input.original_input_text",
        "review_item.canonical",
        "ai_canonical.description",
        "human_edit.description",
    ),
    "product_type": (
        "product_type",
        "category",
        "ai_canonical.product_type",
        "human_edit.product_type",
    ),
}


class RiskAnalysisResult(TypedDict):
    risk_score: int
    warnings: list[str]
    missing_fields: list[str]
    exaggeration_keywords: list[str]
    unsafe_claims: list[str]


def _get_path(payload: ProductPayload, path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping) or isinstance(value, Sequence):
        return bool(value)
    return True


def _field_present(payload: ProductPayload, candidates: Sequence[str]) -> bool:
    return any(_has_meaningful_value(_get_path(payload, path)) for path in candidates)


def _string_parts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_string_parts(item))
        return parts
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        parts = []
        for item in value:
            parts.extend(_string_parts(item))
        return parts
    return [str(value)]


def extract_product_text(product: ProductPayload) -> str:
    return " ".join(_string_parts(product)).lower()


def detect_exaggeration_keywords(product: ProductPayload) -> list[str]:
    text = extract_product_text(product)
    return [keyword for keyword in EXAGGERATION_KEYWORDS if keyword in text]


def detect_unsafe_claims(product: ProductPayload) -> list[str]:
    text = extract_product_text(product)
    return [keyword for keyword in UNSAFE_CLAIM_KEYWORDS if keyword in text]


def detect_missing_fields(product: ProductPayload) -> list[str]:
    return [
        field_name
        for field_name, candidates in REQUIRED_FIELD_GROUPS.items()
        if not _field_present(product, candidates)
    ]


def calculate_risk_score(
    exaggeration_keywords: Sequence[str],
    unsafe_claims: Sequence[str],
    missing_fields: Sequence[str],
) -> int:
    score = 0
    score += min(len(exaggeration_keywords) * 12, 30)
    score += min(len(unsafe_claims) * 18, 45)
    score += min(len(missing_fields) * 10, 25)
    return max(0, min(100, score))


def analyze_risk(product: ProductPayload) -> RiskAnalysisResult:
    exaggeration_keywords = detect_exaggeration_keywords(product)
    unsafe_claims = detect_unsafe_claims(product)
    missing_fields = detect_missing_fields(product)

    warnings = [
        f"Exaggeration keyword detected: {keyword}"
        for keyword in exaggeration_keywords
    ]
    warnings.extend(
        f"Potential unsafe claim detected: {claim}" for claim in unsafe_claims
    )
    warnings.extend(f"Missing product field: {field}" for field in missing_fields)

    return {
        "risk_score": calculate_risk_score(
            exaggeration_keywords,
            unsafe_claims,
            missing_fields,
        ),
        "warnings": warnings,
        "missing_fields": missing_fields,
        "exaggeration_keywords": exaggeration_keywords,
        "unsafe_claims": unsafe_claims,
    }
