"""Deterministic mock suggestion generation for K13-B."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .risk_engine import RiskAnalysisResult

ProductPayload = Mapping[str, Any]


def _get_path(payload: ProductPayload, path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _first_text(payload: ProductPayload, paths: Sequence[str]) -> str:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_collection(payload: ProductPayload, paths: Sequence[str]) -> bool:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, Mapping) or isinstance(value, Sequence):
            if not isinstance(value, str) and bool(value):
                return True
    return False


def generate_suggestions(
    product: ProductPayload,
    risk_analysis: RiskAnalysisResult,
) -> list[str]:
    suggestions: list[str] = []
    title = _first_text(
        product,
        (
            "title",
            "product_name_en",
            "name",
            "ai_canonical.title",
            "human_edit.title",
        ),
    )
    description = _first_text(
        product,
        (
            "description",
            "short_description_en",
            "long_description_en",
            "ai_canonical.description",
            "human_edit.description",
            "review_item.canonical",
            "raw_input_text",
        ),
    )
    product_type = _first_text(product, ("product_type", "category"))

    if not title:
        suggestions.append("Add a concise product title before review.")
    elif len(title) < 35:
        suggestions.append("Improve the title with product type, material, and key use case.")
    elif len(title) > 90:
        suggestions.append("Shorten the title so it stays readable in product listings.")

    if product_type and product_type.lower() not in title.lower():
        suggestions.append("Include the product type in the title for clearer search intent.")

    if not description:
        suggestions.append("Add a canonical product description from the raw input.")
    elif len(description) < 80:
        suggestions.append("Expand the description with use case, material, and buyer benefit.")

    if not _has_collection(
        product,
        (
            "features",
            "bullet_points",
            "original_json.bullet_points",
            "raw_input.original_json.bullet_points",
            "ai_canonical.features",
            "human_edit.features",
        ),
    ):
        suggestions.append("Add missing selling points as reviewer-visible bullet facts.")

    if risk_analysis["exaggeration_keywords"]:
        suggestions.append("Replace absolute or superiority wording with verifiable facts.")

    if risk_analysis["unsafe_claims"]:
        suggestions.append("Move safety or compliance claims into human review before approval.")

    if not suggestions:
        suggestions.append("Review canonical fields for final tone, keyword balance, and clarity.")

    return suggestions
