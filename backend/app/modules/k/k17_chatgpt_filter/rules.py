"""K17-B deterministic filter rule engine.

This module applies local keyword and competitor filtering rules only. It does
not call ChatGPT, Claude, C14, external providers, ranking systems, SEO logic,
or production/staging services.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .schema import ChatGPTFilterInput, ChatGPTFilterOutput

K17_B_MODE = "rule_only"
K17_AI_ACCESS = False
K17_EXTERNAL_ACCESS = False

_MIN_KEYWORD_LENGTH = 2
_MAX_KEYWORD_LENGTH = 40
_NOISE_KEYWORDS = {
    "ads",
    "cheap spam",
    "click here",
    "free",
    "login",
    "signup",
}
_COMMERCIAL_INTENT_TERMS = {
    "best",
    "buy",
    "portable",
    "price",
    "professional",
    "review",
    "wholesale",
}
_SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}
_ECOMMERCE_DOMAIN_MARKERS = (
    "aliexpress",
    "amazon",
    "ebay",
    "etsy",
    "shopify",
    "walmart",
)
_INVALID_LINK_MARKERS = (
    "404",
    "clickid",
    "login",
    "not-found",
    "redirect",
    "redir",
    "signup",
    "track",
    "utm_",
    "utm=",
)


class K17FilterRuleEngine:
    """Rule-only keyword and competitor filter for K17-B."""

    def filter_keywords(self, keywords: list[str]) -> list[str]:
        return self._apply_keyword_rules(keywords)

    def filter_competitors(self, competitors: list[str]) -> list[str]:
        return self._apply_competitor_rules(competitors)

    def build_rule_output(
        self,
        keywords: list[str],
        competitors: list[str],
        serp_bundle: object | None = None,
    ) -> dict[str, object]:
        filtered_keywords = self.filter_keywords(keywords)
        filtered_competitors = self.filter_competitors(competitors)
        return {
            "filtered_keywords": filtered_keywords,
            "filtered_competitors": filtered_competitors,
            "market_signals": self.build_market_signals(
                filtered_keywords,
                filtered_competitors,
                serp_bundle,
            ),
        }

    def to_contract_output(
        self,
        filter_input: ChatGPTFilterInput,
    ) -> ChatGPTFilterOutput:
        rule_output = self.build_rule_output(
            keywords=filter_input.keywords,
            competitors=filter_input.competitor_links,
            serp_bundle=filter_input.serp_bundle,
        )
        selected_keywords = list(rule_output["filtered_keywords"])
        filtered_competitors = list(rule_output["filtered_competitors"])
        return ChatGPTFilterOutput(
            product_id=self._product_id_for(filter_input),
            selected_keywords=selected_keywords,
            filtered_competitors=filtered_competitors,
            market_signals=list(rule_output["market_signals"]),
            reasoning="deterministic_rule_engine",
            confidence_score=self._confidence_score(
                selected_keywords,
                filtered_competitors,
            ),
            risk_flags=self._risk_flags(
                selected_keywords,
                filtered_competitors,
            ),
        )

    @staticmethod
    def _product_id_for(filter_input: ChatGPTFilterInput) -> str:
        product_id = filter_input.product_context.get("product_id", "")
        if not product_id:
            product_id = getattr(filter_input.serp_bundle, "product_id", "")
        return " ".join(str(product_id).strip().split())

    def build_market_signals(
        self,
        filtered_keywords: list[str],
        filtered_competitors: list[str],
        serp_bundle: object | None = None,
    ) -> list[str]:
        competitor_candidates = self._candidate_competitor_count(serp_bundle)
        commercial_density = self._commercial_density_score(filtered_keywords)
        competitor_density = self._competitor_density_score(
            filtered_competitors,
            competitor_candidates,
        )
        ecommerce_competitors = sum(
            1
            for competitor in filtered_competitors
            if self._is_ecommerce_domain(competitor)
        )
        return [
            f"commercial_density_score={commercial_density:.2f}",
            f"competitor_density_score={competitor_density:.2f}",
            f"keyword_count={len(filtered_keywords)}",
            f"competitor_count={len(filtered_competitors)}",
            f"ecommerce_competitor_count={ecommerce_competitors}",
        ]

    def _apply_keyword_rules(self, keywords: list[str]) -> list[str]:
        accepted_keywords: list[str] = []
        for keyword in keywords:
            normalized_keyword = self._normalize_keyword(keyword)
            if not normalized_keyword:
                continue
            if not self._keyword_length_is_valid(normalized_keyword):
                continue
            if self._is_noise_keyword(normalized_keyword):
                continue
            accepted_keywords.append(normalized_keyword)
        return self._dedupe(accepted_keywords)

    def _apply_competitor_rules(self, competitors: list[str]) -> list[str]:
        accepted_competitors: list[str] = []
        for competitor in competitors:
            normalized_competitor = self._normalize_competitor(competitor)
            if not normalized_competitor:
                continue
            if self._is_invalid_link(competitor):
                continue
            if self._is_blocked_social_domain(normalized_competitor, competitor):
                continue
            accepted_competitors.append(normalized_competitor)
        return self._dedupe(accepted_competitors)

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        return " ".join(keyword.strip().lower().split())

    @staticmethod
    def _keyword_length_is_valid(keyword: str) -> bool:
        return _MIN_KEYWORD_LENGTH <= len(keyword) <= _MAX_KEYWORD_LENGTH

    @staticmethod
    def _is_noise_keyword(keyword: str) -> bool:
        return any(noise in keyword for noise in _NOISE_KEYWORDS)

    @staticmethod
    def _normalize_competitor(competitor: str) -> str:
        value = competitor.strip().lower()
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        domain = parsed.netloc or parsed.path
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split("/")[0]

    @staticmethod
    def _is_invalid_link(link: str) -> bool:
        normalized_link = link.strip().lower()
        return any(marker in normalized_link for marker in _INVALID_LINK_MARKERS)

    @staticmethod
    def _is_blocked_social_domain(domain: str, original_link: str) -> bool:
        normalized_link = original_link.lower()
        if domain == "shop.tiktok.com":
            return False
        if domain == "tiktok.com" and "/shop" in normalized_link:
            return False
        if domain.endswith(".tiktok.com") and "/shop" in normalized_link:
            return False
        return any(
            domain == social_domain or domain.endswith(f".{social_domain}")
            for social_domain in _SOCIAL_DOMAINS
        )

    @staticmethod
    def _is_ecommerce_domain(domain: str) -> bool:
        return any(marker in domain for marker in _ECOMMERCE_DOMAIN_MARKERS)

    @staticmethod
    def _commercial_density_score(keywords: list[str]) -> float:
        if not keywords:
            return 0.0

        commercial_keywords = sum(
            1
            for keyword in keywords
            if any(term in keyword.split() for term in _COMMERCIAL_INTENT_TERMS)
        )
        return commercial_keywords / len(keywords)

    @staticmethod
    def _competitor_density_score(
        competitors: list[str],
        competitor_candidates: int,
    ) -> float:
        if competitor_candidates <= 0:
            return 0.0
        return min(1.0, len(competitors) / competitor_candidates)

    @staticmethod
    def _candidate_competitor_count(serp_bundle: object | None) -> int:
        organic_results = getattr(serp_bundle, "organic_results", None)
        if not organic_results:
            return 0
        return len(organic_results)

    @staticmethod
    def _confidence_score(
        selected_keywords: list[str],
        filtered_competitors: list[str],
    ) -> float:
        keyword_signal = min(0.5, len(selected_keywords) * 0.05)
        competitor_signal = min(0.4, len(filtered_competitors) * 0.1)
        return round(0.1 + keyword_signal + competitor_signal, 2)

    @staticmethod
    def _risk_flags(
        selected_keywords: list[str],
        filtered_competitors: list[str],
    ) -> list[str]:
        risk_flags = []
        if not selected_keywords:
            risk_flags.append("no_keywords_after_rules")
        if not filtered_competitors:
            risk_flags.append("no_competitors_after_rules")
        return risk_flags

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
    "K17FilterRuleEngine",
    "K17_B_MODE",
    "K17_AI_ACCESS",
    "K17_EXTERNAL_ACCESS",
]
