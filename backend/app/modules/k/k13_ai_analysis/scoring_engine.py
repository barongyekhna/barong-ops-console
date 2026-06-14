"""Deterministic mock scoring for K13-B."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

ProductPayload = Mapping[str, Any]


class ProductScoreResult(TypedDict):
    seo_score: int
    clarity_score: int
    completeness_score: int


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


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


def _has_value(payload: ProductPayload, paths: Sequence[str]) -> bool:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Mapping) or isinstance(value, Sequence):
            if not isinstance(value, str) and bool(value):
                return True
        if value is not None and not isinstance(value, (str, Mapping, Sequence)):
            return True
    return False


def calculate_seo_score(product: ProductPayload) -> int:
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
        ),
    )
    score = 35

    if 35 <= len(title) <= 90:
        score += 30
    elif title:
        score += 15

    if len(description) >= 80:
        score += 20
    elif description:
        score += 10

    if _has_value(product, ("keywords", "ai_canonical.keywords", "human_edit.keywords")):
        score += 15

    return _clamp_score(score)


def calculate_clarity_score(product: ProductPayload) -> int:
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
    score = 45

    if description:
        score += 20
    if 80 <= len(description) <= 500:
        score += 20
    if "." in description or "," in description:
        score += 10
    if len(description.split()) > 120:
        score -= 15

    return _clamp_score(score)


def calculate_completeness_score(product: ProductPayload) -> int:
    field_groups = (
        ("title", "product_name_en", "name", "ai_canonical.title", "human_edit.title"),
        (
            "description",
            "short_description_en",
            "long_description_en",
            "ai_canonical.description",
            "human_edit.description",
            "review_item.canonical",
        ),
        ("raw_input_text", "raw_input.original_input_text", "review_item.raw"),
        ("product_type", "category"),
        ("features", "ai_canonical.features", "human_edit.features"),
        ("specs", "ai_canonical.specs", "human_edit.specs"),
    )
    present = sum(1 for group in field_groups if _has_value(product, group))
    return _clamp_score(round((present / len(field_groups)) * 100))


def score_product(product: ProductPayload) -> ProductScoreResult:
    return {
        "seo_score": calculate_seo_score(product),
        "clarity_score": calculate_clarity_score(product),
        "completeness_score": calculate_completeness_score(product),
    }
