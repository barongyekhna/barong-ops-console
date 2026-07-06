"""Shared product image helpers for R-series product surfaces."""

from __future__ import annotations

from typing import Any


def product_image_candidates(
    *,
    asin: str | None,
    image_url: str | None = None,
    features: dict[str, Any] | None = None,
) -> list[str]:
    candidates: list[str] = []
    _add_image_candidate(candidates, image_url)
    for value in _feature_image_values(features or {}):
        _add_image_candidate(candidates, value)

    cleaned_asin = str(asin or "").strip().upper()
    if len(cleaned_asin) == 10 and cleaned_asin.isalnum():
        _add_image_candidate(
            candidates,
            f"https://m.media-amazon.com/images/P/{cleaned_asin}.01._SL160_.jpg",
        )
        _add_image_candidate(
            candidates,
            f"https://images-na.ssl-images-amazon.com/images/P/{cleaned_asin}.01._SCLZZZZZZZ_.jpg",
        )
    return candidates


def primary_product_image_url(
    *,
    asin: str | None,
    image_url: str | None = None,
    features: dict[str, Any] | None = None,
) -> str | None:
    candidates = product_image_candidates(asin=asin, image_url=image_url, features=features)
    return candidates[0] if candidates else None


def _add_image_candidate(candidates: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    cleaned = value.strip()
    if not cleaned:
        return
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    if not cleaned.startswith(("http://", "https://")):
        if _looks_like_keepa_image_name(cleaned):
            _add_image_candidate(
                candidates,
                f"https://images-na.ssl-images-amazon.com/images/I/{cleaned}",
            )
            _add_image_candidate(candidates, f"https://m.media-amazon.com/images/I/{cleaned}")
        return
    for candidate in _url_variants(cleaned):
        if candidate not in candidates:
            candidates.append(candidate)


def _url_variants(url: str) -> list[str]:
    variants = [url]
    if "images-na.ssl-images-amazon.com/images/I/" in url:
        variants.append(
            url.replace(
                "https://images-na.ssl-images-amazon.com/images/I/",
                "https://m.media-amazon.com/images/I/",
            )
        )
    if "m.media-amazon.com/images/I/" in url:
        variants.append(
            url.replace(
                "https://m.media-amazon.com/images/I/",
                "https://images-na.ssl-images-amazon.com/images/I/",
            )
        )
    if "images-na.ssl-images-amazon.com/images/P/" in url:
        variants.append(
            url.replace(
                "https://images-na.ssl-images-amazon.com/images/P/",
                "https://m.media-amazon.com/images/P/",
            ).replace("._SCLZZZZZZZ_", "._SL160_")
        )
    return variants


def _feature_image_values(features: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "image_candidates",
        "images",
        "image_urls",
        "imageUrl",
        "image_url",
        "imagesCSV",
        "images_csv",
    ):
        _collect_image_values(features.get(key), values)
    return values


def _collect_image_values(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        parts = value.split(",") if "," in value and not value.startswith("http") else [value]
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                output.append(cleaned)
        return
    if isinstance(value, list):
        for item in value:
            _collect_image_values(item, output)


def _looks_like_keepa_image_name(value: str) -> bool:
    lowered = value.lower()
    return lowered.endswith((".jpg", ".jpeg", ".png", ".webp")) and "/" not in value
