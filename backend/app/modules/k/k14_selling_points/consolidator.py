"""K14-B suggestion consolidation layer.

This module adapts K13 analysis output into the K14-A ProductSellingPoints
schema. It does not implement AI generation, call external providers, mutate
K13 engines, register API routes, or write persistence state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .models import BulletPoint, ProductSellingPoints

ProductPayload = Any
K13Output = Mapping[str, Any]

_ALLOWED_SOURCES = {
    "k13_ai_engine",
    "k13_bridge",
    "manual_input",
    "future_live_ai",
}

_KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "so",
    "the",
    "to",
    "with",
    "your",
}

_MARKET_HINTS = {
    "amazon": ("amazon",),
    "shopify": ("shopify",),
    "tiktok_shop": ("tiktok", "tiktok_shop", "short video", "influencer"),
}


class K13Engine(Protocol):
    """Minimal K13-compatible analysis engine contract."""

    def analyze(self, product: ProductPayload) -> K13Output:
        """Return raw K13 analysis output for a product payload."""
        ...


class K14SuggestionConsolidator:
    """Convert K13 suggestions into the normalized K14-A structure."""

    def __init__(self, k13_engine: K13Engine, k14_schema: type[ProductSellingPoints]):
        self.k13_engine = k13_engine
        self.schema = k14_schema

    def convert(self, product: ProductPayload) -> ProductSellingPoints:
        k13_output = self.k13_engine.analyze(product)

        return self.schema(
            product_id=str(
                self._product_value(
                    product,
                    ("id", "product_id", "product_key", "sku", "source_record_id"),
                    "unknown",
                )
            ),
            title=str(
                self._product_value(
                    product,
                    ("title", "product_name_en", "name", "product_type"),
                    "Untitled product",
                )
            ),
            raw_input=str(
                self._product_value(
                    product,
                    (
                        "raw_input",
                        "raw_input_text",
                        "description",
                        "long_description_en",
                        "short_description_en",
                    ),
                    self._product_value(
                        product,
                        ("title", "product_name_en", "name"),
                        "unknown",
                    ),
                )
            ),
            language=str(
                self._product_value(
                    product,
                    ("language", "raw_input_language", "canonical_language"),
                    "en",
                )
            ).lower(),
            bullets=self._map_bullets(k13_output),
            seo_bullets=self._map_seo(k13_output),
            seo_keywords=self._map_keywords(k13_output),
            market_tags=self._map_market(product),
            source=self._map_source(k13_output),
            confidence_score=self._confidence_score(k13_output.get("confidence", 0.5)),
        )

    def _map_bullets(self, k13_output: K13Output) -> list[BulletPoint]:
        bullets: list[BulletPoint] = []

        for item in self._as_list(k13_output.get("suggestions", [])):
            text = self._item_text(item)
            if not text:
                continue

            item_type = self._item_type(item)
            if item_type == "risk":
                category = "feature"
                importance = 90
            elif item_type == "suggestion":
                category = "benefit"
                importance = 70
            elif item_type == "usage":
                category = "usage"
                importance = 60
            else:
                category = "spec"
                importance = 50

            bullets.append(
                BulletPoint(
                    text=text,
                    category=category,
                    importance_score=importance,
                )
            )

        return bullets

    def _map_seo(self, k13_output: K13Output) -> list[str]:
        seo_sources = (
            k13_output.get("seo_bullets"),
            k13_output.get("seo_suggestions"),
            k13_output.get("suggestions"),
        )
        return self._dedupe_text(
            self._item_text(item)
            for source in seo_sources
            for item in self._as_list(source)
        )

    def _map_keywords(self, k13_output: K13Output) -> list[str]:
        keyword_candidates = [
            *self._as_list(k13_output.get("seo_keywords")),
            *self._as_list(k13_output.get("keywords")),
        ]

        if not keyword_candidates:
            keyword_candidates = [
                token
                for item in self._as_list(k13_output.get("suggestions", []))
                for token in self._tokenize_keywords(self._item_text(item))
            ]

        normalized = (
            str(keyword).strip().lower()
            for keyword in keyword_candidates
            if str(keyword).strip()
        )
        return self._dedupe_text(normalized, limit=10)

    def _map_market(self, product: ProductPayload) -> list[str]:
        explicit_tags = self._product_value(
            product,
            ("market_tags", "markets", "platforms", "channels"),
            [],
        )
        tags = [
            str(tag).strip().lower()
            for tag in self._as_list(explicit_tags)
            if str(tag).strip()
        ]

        product_text = " ".join(
            str(value)
            for value in (
                self._product_value(product, ("title", "product_name_en", "name"), ""),
                self._product_value(product, ("category", "product_type"), ""),
                self._product_value(
                    product,
                    ("description", "short_description_en", "long_description_en"),
                    "",
                ),
            )
            if value
        ).lower()

        for tag, hints in _MARKET_HINTS.items():
            if any(hint in product_text for hint in hints):
                tags.append(tag)

        if any(
            hint in product_text
            for hint in (
                "accessory",
                "beauty",
                "electronics",
                "home",
                "kitchen",
                "office",
                "tool",
            )
        ):
            tags.extend(("amazon", "shopify"))

        if any(
            hint in product_text
            for hint in ("beauty", "fashion", "gift", "gadget", "trending")
        ):
            tags.append("tiktok_shop")

        mapped_tags = [self._normalize_market_tag(tag) for tag in tags]
        deduped_tags = self._dedupe_text(tag for tag in mapped_tags if tag)
        return deduped_tags or ["general"]

    def _map_source(self, k13_output: K13Output) -> str:
        output_source = str(k13_output.get("source", "")).strip()
        if output_source in _ALLOWED_SOURCES:
            return output_source

        engine = self.k13_engine
        engine_name = getattr(engine, "__name__", engine.__class__.__name__).lower()
        engine_module = getattr(engine, "__module__", engine.__class__.__module__).lower()

        if "bridge" in engine_name or "k13_ai_bridge" in engine_module:
            return "k13_bridge"

        return "k13_ai_engine"

    @staticmethod
    def _product_value(
        product: ProductPayload,
        keys: Sequence[str],
        default: Any,
    ) -> Any:
        for key in keys:
            if isinstance(product, Mapping) and key in product:
                value = product[key]
            else:
                value = getattr(product, key, None)

            if value is not None and value != "":
                return value

        return default

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Mapping):
            return [value]
        if isinstance(value, Sequence):
            return list(value)
        return [value]

    @staticmethod
    def _item_text(item: Any) -> str:
        if isinstance(item, str):
            return item.strip()

        if isinstance(item, Mapping):
            for key in ("text", "message", "suggestion", "content", "value"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        for attr in ("text", "message", "suggestion", "content", "value"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    @staticmethod
    def _item_type(item: Any) -> str:
        if isinstance(item, Mapping):
            value = item.get("type") or item.get("category") or item.get("kind")
        else:
            value = (
                getattr(item, "type", None)
                or getattr(item, "category", None)
                or getattr(item, "kind", None)
            )

        if isinstance(value, str) and value.strip():
            return value.strip().lower()

        return "suggestion"

    @staticmethod
    def _tokenize_keywords(text: str) -> list[str]:
        tokens: list[str] = []
        current: list[str] = []

        for char in text.lower():
            if char.isalnum():
                current.append(char)
                continue

            if current:
                token = "".join(current)
                if len(token) > 2 and token not in _KEYWORD_STOPWORDS:
                    tokens.append(token)
                current = []

        if current:
            token = "".join(current)
            if len(token) > 2 and token not in _KEYWORD_STOPWORDS:
                tokens.append(token)

        return tokens

    @staticmethod
    def _normalize_market_tag(tag: str) -> str:
        normalized = tag.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"tiktok", "tik_tok", "tiktokshop"}:
            return "tiktok_shop"
        return normalized

    @staticmethod
    def _confidence_score(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.5

        return max(0.0, min(1.0, score))

    @staticmethod
    def _dedupe_text(values: Any, limit: int | None = None) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()

        for value in values:
            text = str(value).strip()
            if not text:
                continue

            key = text.lower()
            if key in seen:
                continue

            deduped.append(text)
            seen.add(key)

            if limit is not None and len(deduped) >= limit:
                break

        return deduped
