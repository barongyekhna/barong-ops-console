"""K18-B deterministic Claude filter rule engine.

This module applies local second-pass validation rules only. It does not call
Claude, ChatGPT, C14, external APIs, ranking systems, SEO logic, backend
services, or production/staging environments.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

K18_B_MODE = "rule_only"
K18_RUNTIME = "disabled"
K18_EXTERNAL_ACCESS = False

K18_B_DATA_FLOW = (
    "K17-F output",
    "K18-A contract",
    "K18-B rule engine",
    "K18-C (future C14 request)",
    "K18-D (response parser)",
)

_COMMERCIAL_TERMS = {
    "best",
    "buy",
    "price",
    "review",
    "wholesale",
}

_KEYWORD_NOISE_TERMS = {
    "ads",
    "affiliate",
    "backlink",
    "bot",
    "click here",
    "coupon generator",
    "free followers",
    "keyword stuffing",
    "login",
    "promo code hack",
    "scraper",
    "seo spam",
    "signup",
    "traffic bot",
}

_IRRELEVANT_EXPANSION_TERMS = {
    "definition",
    "download",
    "job",
    "jobs",
    "meaning",
    "pdf",
    "salary",
    "template",
    "torrent",
    "training",
    "used for",
    "what is",
    "wikipedia",
}

_INTENT_STOPWORDS = {
    "and",
    "best",
    "buy",
    "for",
    "from",
    "near",
    "online",
    "price",
    "review",
    "reviews",
    "shop",
    "the",
    "wholesale",
    "with",
}

_SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

_ECOMMERCE_DOMAIN_MARKERS = (
    "aliexpress",
    "amazon",
    "ebay",
    "myshopify",
    "shop.app",
    "shopify",
)

_NON_COMPETITOR_DOMAIN_MARKERS = (
    "blogspot.",
    "docs.",
    "help.",
    "medium.com",
    "support.",
    "wikipedia.org",
)

_TRACKING_QUERY_KEYS = {
    "affid",
    "affiliate",
    "campaign",
    "click_id",
    "clickid",
    "fbclid",
    "gclid",
    "mc_cid",
    "msclkid",
    "ref",
    "tag",
}

_TRACKING_LINK_MARKERS = (
    "/affiliate/",
    "/click?",
    "/go/",
    "/out/",
    "/redirect",
    "/redir",
    "/track",
    "affiliate_id=",
    "clickid=",
    "redirect=",
    "tracking",
    "utm_",
)


class K18FilterRuleEngine:
    """Rule-only Claude second-pass validator for K18-B."""

    def filter_keywords(self, keywords: list[str]) -> list[str]:
        return self._apply_keyword_rules(keywords)

    def filter_competitors(self, competitors: list[str]) -> list[str]:
        return self._apply_competitor_rules(competitors)

    def build_rule_output(
        self,
        keywords: list[str],
        competitors: list[str],
        market_signals: list[str] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        """Build a deterministic K18-B output payload for future K18-C."""

        final_keywords = self.filter_keywords(keywords)
        validated_competitors = self.filter_competitors(competitors)
        market_validation = self.build_market_validation(
            raw_keywords=keywords,
            raw_competitors=competitors,
            final_keywords=final_keywords,
            validated_competitors=validated_competitors,
            market_signals=market_signals or [],
        )

        return {
            "final_keywords": final_keywords,
            "validated_competitors": validated_competitors,
            "market_validation": market_validation,
            "reasoning": self._reasoning(context),
            "confidence_score": self._confidence_score(market_validation),
            "risk_flags": self._risk_flags(final_keywords, validated_competitors),
        }

    def build_market_validation(
        self,
        raw_keywords: list[str],
        raw_competitors: list[str],
        final_keywords: list[str],
        validated_competitors: list[str],
        market_signals: list[str] | None = None,
    ) -> dict[str, object]:
        """Generate deterministic market validation scores."""

        return {
            "competitor_density_score": self._competitor_density_score(
                raw_competitors,
                validated_competitors,
            ),
            "commercial_intensity_score": self._commercial_intensity_score(
                final_keywords,
            ),
            "keyword_quality_score": self._keyword_quality_score(
                raw_keywords,
                final_keywords,
            ),
            "keyword_count": len(final_keywords),
            "competitor_count": len(validated_competitors),
            "ecommerce_competitor_count": sum(
                1
                for competitor in validated_competitors
                if self._is_ecommerce_domain(competitor)
            ),
            "source_market_signal_count": len(market_signals or []),
        }

    def build_from_contract_input(self, filter_input: object) -> dict[str, object]:
        """Consume a K18-A-shaped object or dict without executing C14."""

        keywords = self._get_list(filter_input, "keywords")
        competitors = self._get_list(filter_input, "competitors")
        market_signals = self._get_list(filter_input, "market_signals")
        context = self._get_mapping(filter_input, "context")
        return self.build_rule_output(
            keywords=keywords,
            competitors=competitors,
            market_signals=market_signals,
            context=context,
        )

    def _apply_keyword_rules(self, keywords: list[str]) -> list[str]:
        intent_terms = self._product_intent_terms(keywords)
        accepted_keywords: list[str] = []

        for keyword in keywords:
            normalized_keyword = self._normalize_keyword(keyword)
            if not normalized_keyword:
                continue
            if self._is_noise_keyword(normalized_keyword):
                continue
            if self._is_irrelevant_expansion(normalized_keyword):
                continue
            if not self._matches_product_intent(normalized_keyword, intent_terms):
                continue
            if not self._has_commercial_intent(normalized_keyword):
                continue
            accepted_keywords.append(normalized_keyword)

        return self._dedupe(accepted_keywords)

    def _apply_competitor_rules(self, competitors: list[str]) -> list[str]:
        accepted_competitors: list[str] = []

        for competitor in competitors:
            normalized_competitor = self._normalize_competitor(competitor)
            if not normalized_competitor:
                continue
            if self._is_tracking_link(competitor):
                continue
            if self._is_blocked_social_domain(normalized_competitor, competitor):
                continue
            if self._is_non_competitor_domain(normalized_competitor):
                continue
            if not self._is_ecommerce_or_official_brand(normalized_competitor):
                continue
            accepted_competitors.append(normalized_competitor)

        return self._dedupe(accepted_competitors)

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        return " ".join(str(keyword).strip().lower().split())

    @staticmethod
    def _has_commercial_intent(keyword: str) -> bool:
        tokens = set(keyword.split())
        return any(term in tokens for term in _COMMERCIAL_TERMS)

    @staticmethod
    def _is_noise_keyword(keyword: str) -> bool:
        return any(noise in keyword for noise in _KEYWORD_NOISE_TERMS)

    @staticmethod
    def _is_irrelevant_expansion(keyword: str) -> bool:
        return any(term in keyword for term in _IRRELEVANT_EXPANSION_TERMS)

    def _matches_product_intent(self, keyword: str, intent_terms: set[str]) -> bool:
        if not intent_terms:
            return True
        return bool(set(keyword.split()) & intent_terms)

    def _product_intent_terms(self, keywords: list[str]) -> set[str]:
        token_counts: Counter[str] = Counter()

        for keyword in keywords:
            normalized_keyword = self._normalize_keyword(keyword)
            if not normalized_keyword or self._is_noise_keyword(normalized_keyword):
                continue
            token_counts.update(
                token
                for token in normalized_keyword.split()
                if self._is_intent_token(token)
            )

        repeated_tokens = {
            token for token, count in token_counts.items() if count >= 2
        }
        if repeated_tokens:
            return repeated_tokens

        return {token for token, _count in token_counts.most_common(3)}

    @staticmethod
    def _is_intent_token(token: str) -> bool:
        return (
            len(token) >= 3
            and token not in _INTENT_STOPWORDS
            and not token.isdigit()
            and token.isascii()
        )

    @staticmethod
    def _normalize_competitor(competitor: str) -> str:
        value = str(competitor).strip().lower()
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        domain = parsed.netloc or parsed.path
        if "@" in domain:
            domain = domain.rsplit("@", 1)[-1]
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.strip(".").split("/")[0]

    @staticmethod
    def _is_tracking_link(link: str) -> bool:
        normalized_link = str(link).strip().lower()
        if any(marker in normalized_link for marker in _TRACKING_LINK_MARKERS):
            return True

        parsed = urlparse(
            normalized_link if "://" in normalized_link else f"https://{normalized_link}"
        )
        query_keys = set(parse_qs(parsed.query).keys())
        if any(key.startswith("utm_") for key in query_keys):
            return True
        return bool(query_keys & _TRACKING_QUERY_KEYS)

    @staticmethod
    def _is_blocked_social_domain(domain: str, original_link: str) -> bool:
        normalized_link = str(original_link).strip().lower()
        if domain == "shop.tiktok.com":
            return False
        if domain.endswith(".tiktok.com") and "/shop" in normalized_link:
            return False
        if domain == "tiktok.com" and "/shop" in normalized_link:
            return False

        return any(
            domain == social_domain or domain.endswith(f".{social_domain}")
            for social_domain in _SOCIAL_DOMAINS
        )

    @staticmethod
    def _is_non_competitor_domain(domain: str) -> bool:
        return any(marker in domain for marker in _NON_COMPETITOR_DOMAIN_MARKERS)

    @staticmethod
    def _is_ecommerce_domain(domain: str) -> bool:
        return any(marker in domain for marker in _ECOMMERCE_DOMAIN_MARKERS)

    def _is_ecommerce_or_official_brand(self, domain: str) -> bool:
        if self._is_ecommerce_domain(domain):
            return True
        return self._is_official_brand_candidate(domain)

    @staticmethod
    def _is_official_brand_candidate(domain: str) -> bool:
        return "." in domain and not domain.startswith(".") and not domain.endswith(".")

    @staticmethod
    def _competitor_density_score(
        raw_competitors: list[str],
        validated_competitors: list[str],
    ) -> float:
        raw_count = len([competitor for competitor in raw_competitors if competitor])
        if raw_count <= 0:
            return 0.0
        return round(min(1.0, len(validated_competitors) / raw_count), 2)

    def _commercial_intensity_score(self, final_keywords: list[str]) -> float:
        if not final_keywords:
            return 0.0

        commercial_keywords = sum(
            1 for keyword in final_keywords if self._has_commercial_intent(keyword)
        )
        return round(commercial_keywords / len(final_keywords), 2)

    @staticmethod
    def _keyword_quality_score(
        raw_keywords: list[str],
        final_keywords: list[str],
    ) -> float:
        raw_count = len([keyword for keyword in raw_keywords if keyword])
        if raw_count <= 0:
            return 0.0
        return round(min(1.0, len(final_keywords) / raw_count), 2)

    @staticmethod
    def _confidence_score(market_validation: Mapping[str, object]) -> float:
        competitor_density = float(
            market_validation.get("competitor_density_score", 0.0)
        )
        commercial_intensity = float(
            market_validation.get("commercial_intensity_score", 0.0)
        )
        keyword_quality = float(market_validation.get("keyword_quality_score", 0.0))
        return round(
            min(
                1.0,
                (competitor_density * 0.3)
                + (commercial_intensity * 0.4)
                + (keyword_quality * 0.3),
            ),
            2,
        )

    @staticmethod
    def _risk_flags(
        final_keywords: list[str],
        validated_competitors: list[str],
    ) -> list[str]:
        risk_flags: list[str] = []
        if not final_keywords:
            risk_flags.append("no_keywords_after_k18_rules")
        if not validated_competitors:
            risk_flags.append("no_competitors_after_k18_rules")
        return risk_flags

    @staticmethod
    def _reasoning(context: Mapping[str, Any] | None) -> str:
        source_reasoning = ""
        if context:
            source_reasoning = str(context.get("reasoning", "")).strip()
        if not source_reasoning:
            return "k18_deterministic_rule_engine"
        return f"k18_deterministic_rule_engine; source_context={source_reasoning}"

    @staticmethod
    def _get_list(value: object, field_name: str) -> list[str]:
        if isinstance(value, Mapping):
            raw_value = value.get(field_name, [])
        else:
            raw_value = getattr(value, field_name, [])
        if not isinstance(raw_value, list):
            return []
        return [str(item) for item in raw_value]

    @staticmethod
    def _get_mapping(value: object, field_name: str) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            raw_value = value.get(field_name, {})
        else:
            raw_value = getattr(value, field_name, {})
        if isinstance(raw_value, Mapping):
            return raw_value
        if hasattr(raw_value, "model_dump"):
            dumped_value = raw_value.model_dump()
            if isinstance(dumped_value, Mapping):
                return dumped_value
        return {}

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = value.strip()
            key = text.lower()
            if not text or key in seen:
                continue
            deduped.append(text)
            seen.add(key)
        return deduped


__all__ = [
    "K18FilterRuleEngine",
    "K18_B_DATA_FLOW",
    "K18_B_MODE",
    "K18_EXTERNAL_ACCESS",
    "K18_RUNTIME",
]
