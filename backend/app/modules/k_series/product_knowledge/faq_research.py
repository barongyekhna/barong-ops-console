"""Evidence extraction and quality gates for PDP FAQ generation.

The module is deterministic and network-free.  The workflow owns Serper calls;
these helpers retain PAA/forum/review provenance and reject specification
paraphrases before copy can reach P-series or FAQPage schema.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from .buyer_display import buyer_display_structured_specs, imperial_measurement


_FORUM_DOMAINS = (
    "reddit.",
    "quora.",
    "stackexchange.",
    "stackoverflow.",
    "forums.",
    "forum.",
    "community.",
)
_REVIEW_TERMS = (
    "review",
    "reviews",
    "complaint",
    "complaints",
    "problem",
    "problems",
    "issue",
    "issues",
    "failure",
    "drawback",
)
_QUESTION_START = re.compile(
    r"^(?:how|what|when|where|which|why|who|can|could|do|does|did|has|have|is|are|"
    r"may|might|must|was|were|will|would|should)\b",
    re.IGNORECASE,
)
_QUESTION_END = re.compile(r"[?？]\s*$")
_ARTICLE_OR_LISTICLE_TITLE = re.compile(
    r"(?:^(?:the\s+)?(?:\d+\s+)?(?:best|top)\b"
    r"|\btested\s*(?:&|and)\s*reviewed\b"
    r"|\bput\s+to\s+the\s+test\b)",
    re.IGNORECASE,
)
# Device-malfunction / repair questions ("why does my pump keep running", "how
# to fix", "won't turn on") are post-purchase troubleshooting, not pre-purchase
# buyer intent, and they invite generic category answers that can contradict how
# THIS product actually works (a submersible pump has no intake hose to "check").
# Reject them from FAQ candidates so the answer generator is never handed a
# malfunction frame it can only resolve with unsafe generic guidance.
_MALFUNCTION_QUESTION = re.compile(
    r"\bhow (?:do|can) (?:i|you) (?:fix|repair|reset|troubleshoot)\b"
    r"|\bhow to (?:fix|repair|reset|troubleshoot)\b"
    r"|\bwhy (?:does|is|are|do|did|won'?t|wo n'?t|isn'?t|does\s?n'?t)\b.{0,40}?"
    r"\b(?:keep|keeps|kept|stop\w*|won'?t|wo n'?t|not work\w*|leak\w*|broken|"
    r"beep\w*|shut\w*|dying|drain\w*|overheat\w*|not charg\w*|turn\w*|start\w*)\b"
    r"|\b(?:not working|stopped working|won'?t turn on|wo n'?t turn on|won'?t charge|"
    r"not charging|no power|keeps? (?:running|leaking|beeping|shutting|turning off)|"
    r"troubleshoot\w*|malfunction\w*)\b",
    re.IGNORECASE,
)
# Keep this list deliberately data-like and easy to extend when brand review
# discovers another competitor leaking out of Serper.  Only distinctive third-
# party names belong here; product/material words would create false positives.
_THIRD_PARTY_BRAND_BLACKLIST = (
    "bisgear",
    "boundless voyage",
    "bulin",
    "coleman",
    "cordura",
    "decathlon",
    "fire-maple",
    "fire maple",
    "gsi",
    "gsi outdoors",
    "jetboil",
    "kelty",
    "mallo me",
    "msr",
    "nemo",
    "odoland",
    "primus",
    "sea to summit",
    "snow peak",
    "stanley",
    "toaks",
    "tritan",
    "vango",
    "widesea",
    "yeti",
)
_BRAND_QUALITY_QUESTION = re.compile(
    r"^is\s+.{1,60}\s+(?:an?\s+)?(?:good|reliable|reputable|legit|quality|premium)\s+brand\b",
    re.IGNORECASE,
)
_IS_PROPER_NAME_QUESTION = re.compile(
    r"^[Ii]s\s+(?:[Tt]he\s+)?"
    r"(?P<brand>[A-Z][A-Za-z0-9&'’.-]{2,}(?:\s+[A-Z][A-Za-z0-9&'’.-]{2,}){0,2})\b"
)
_VS_COMPARISON = re.compile(r"\bvs(?:\.|\b)", re.IGNORECASE)
_COMPARISON_TRAILING_CONTEXT = re.compile(
    r"(?:[?？,;:]|\s+\b(?:"
    r"is|are|do|does|has|have|will|lasts|"
    r"better|best|worse|safer|easier|harder|lighter|heavier|faster|slower|"
    r"cheaper|stronger|weaker|longer|shorter|more|less|preferable|recommended|"
    r"different|convenient|durable|compare|compared|pros|cons|"
    r"for|in|during|when|with|on|at|under|to"
    r")\b)",
    re.IGNORECASE,
)
_GENERIC_COMPARISON_TOKENS = {
    "abs",
    "alcohol",
    "aluminum",
    "aluminium",
    "anodized",
    "backpacking",
    "barong",
    "bpa",
    "butane",
    "camp",
    "camping",
    "canister",
    "carbon",
    "cast",
    "ceramic",
    "cold",
    "co2",
    "cooking",
    "cookware",
    "double",
    "durable",
    "easy",
    "electric",
    "free",
    "fuel",
    "gas",
    "hard",
    "iron",
    "isobutane",
    "liquid",
    "lpg",
    "nonstick",
    "open",
    "outdoor",
    "pan",
    "pans",
    "pfoa",
    "plastic",
    "portable",
    "pot",
    "pots",
    "propane",
    "ptfe",
    "pvc",
    "reliable",
    "safe",
    "set",
    "sets",
    "single",
    "steel",
    "stove",
    "stoves",
    "stainless",
    "titanium",
    "this",
    "suitable",
    "travel",
    "wall",
    "weather",
    "white",
    "wood",
    "yekhna",
}
_COMPARISON_SCAFFOLD_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "best",
    "better",
    "between",
    "can",
    "choose",
    "compare",
    "compared",
    "comparing",
    "cons",
    "could",
    "difference",
    "differences",
    "different",
    "does",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "last",
    "lasts",
    "longer",
    "more",
    "or",
    "of",
    "pick",
    "pros",
    "safer",
    "should",
    "the",
    "than",
    "use",
    "using",
    "versus",
    "we",
    "when",
    "with",
    "what",
    "which",
    "worse",
}
_TECHNICAL_ENTITY_ALLOWLIST = {
    "abs",
    "api",
    "bpa",
    "btu",
    "cfm",
    "co2",
    "db",
    "dba",
    "dtc",
    "eva",
    "faq",
    "fcc",
    "fda",
    "hdpe",
    "led",
    "lifepo4",
    "liion",
    "lpg",
    "nbr",
    "nimh",
    "paa",
    "pdp",
    "pet",
    "pfoa",
    "pp",
    "pom",
    "ptfe",
    "pvc",
    "psi",
    "rpm",
    "seo",
    "sku",
    "tpu",
    "tpr",
    "tsa",
    "usa",
    "usb",
    "usbc",
    "uv",
    "wifi",
}
_MIXED_CASE_TECHNICAL_MEASUREMENT = re.compile(
    r"^(?:\d+(?:\.\d+)?(?:ah|mah|wh|kwh|db|rpm|cfm|psi)|"
    r"(?:ac|dc)\d+(?:\.\d+)?v?|ipx\d+|sus\d+|upf\d+|usb-[a-z0-9]+)$",
    re.IGNORECASE,
)
_GENERIC_ENTITY_TOKENS = {
    "alloy",
    "bamboo",
    "borosilicate",
    "charging",
    "clean",
    "coated",
    "copper",
    "die",
    "dry",
    "enough",
    "enamel",
    "fabric",
    "flame",
    "fiber",
    "food",
    "grade",
    "glass",
    "high",
    "keep",
    "natural",
    "nylon",
    "oxford",
    "pack",
    "place",
    "polyester",
    "polypropylene",
    "protection",
    "ripstop",
    "silicone",
    "store",
    "tempered",
}
_TITLECASE_PRODUCT_ENTITY = re.compile(
    r"\b(?P<brand>[A-Z][A-Za-z0-9&'’.-]{2,})\s+"
    r"(?:(?i:camping|outdoor)\s+)?"
    r"(?i:cookware|cooksets?|stoves?|tents?|gear|products?|kits?|pans?|pots?|"
    r"backpacks?|sleeping\s+bags?|coolers?|lanterns?)\b"
)
_PROPER_NAME_REVIEW = re.compile(
    r"\b(?P<brand>[A-Z][A-Za-z0-9&'’.-]{2,}(?:\s+[A-Z][A-Za-z0-9&'’.-]{2,}){0,2})\s+"
    r"(?:(?:camping|outdoor|cookware|cookset|stove|gear|product)\s+){0,2}reviews?\b"
)
_SPEC_PARAPHRASE = re.compile(
    r"^(?:(?:what|which)\s+(?:is|are)\s+(?:the\s+)?"
    r"(?:dimensions?|size|weight|material|capacity|color|colour|quantity|voltage|wattage)"
    r"|how\s+(?:big|large|heavy|wide|long|tall)\s+(?:is|are)\b"
    r"|how\s+much\s+does\s+.+\s+weigh\b)",
    re.IGNORECASE,
)
_SPEC_PARAPHRASE_ZH = re.compile(
    r"^(?:这个|该|产品)?(?:尺寸|大小|重量|多重|材质|材料|容量|颜色|电压|功率|规格|参数)(?:是|有|多少|什么)"
)
_ABSOLUTE_SAFETY = re.compile(
    r"\b(?:completely safe|perfectly safe|safe indoors?|hazard[- ]free|guaranteed|will never|100% safe)\b",
    re.IGNORECASE,
)
_PRODUCT_ASSERTION = re.compile(
    r"\b(?:this|the product|the item|it)\b.{0,45}\b(?:is|can|has|provides|supports|works|will)\b",
    re.IGNORECASE,
)
_ANSWER_CLAIM_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wind", ("windproof", "wind resistant", "wind-resistant")),
    ("water", ("waterproof", "water resistant", "water-resistant")),
    ("indoor", ("indoor", "indoors", "home use")),
    ("safety", ("safe", "safety", "hazard-free")),
    ("altitude", ("high altitude", "elevation")),
    ("cold", ("cold weather", "low temperature", "winter")),
)
_SPEC_NUMBER = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?")
_SPEC_FACT_VALUE_KEYS = {
    "value",
    "raw_value",
    "value_en",
    "raw_value_en",
    "min",
    "max",
}
_SPEC_METADATA_SUBTREE_KEYS = {
    "schema_version",
    "source",
    "buyer_translation",
    "customer_translations",
    "translation_requests",
    "package_includes_source",
    "source_url",
    "url",
    "platform",
    "evidence_type",
    "retrieved_at",
    "observed_at",
    "created_at",
    "updated_at",
}


def _clean_text(value: Any, *, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _question_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_third_party_brand(value: Any) -> bool:
    normalized = f" {_question_key(_clean_text(value, limit=2000))} "
    return any(
        f" {_question_key(brand)} " in normalized
        for brand in _THIRD_PARTY_BRAND_BLACKLIST
    )


def _comparison_side_is_generic(value: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", value.casefold()))
    tokens.difference_update(_COMPARISON_SCAFFOLD_TOKENS)
    return bool(tokens) and tokens <= _GENERIC_COMPARISON_TOKENS


def _entity_word_stem(value: str) -> str:
    return re.sub(r"(?:['’]s|-brand)$", "", value, flags=re.IGNORECASE)


def _entity_token_is_technical(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return normalized in _TECHNICAL_ENTITY_ALLOWLIST or bool(
        _MIXED_CASE_TECHNICAL_MEASUREMENT.fullmatch(value)
    )


def _entity_atom_is_generic(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return bool(
        _entity_token_is_technical(value)
        or normalized in _GENERIC_COMPARISON_TOKENS
        or normalized in _COMPARISON_SCAFFOLD_TOKENS
        or normalized in _GENERIC_ENTITY_TOKENS
    )


def _entity_phrase_is_generic(value: str) -> bool:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'’./-]*", value)
    if not tokens:
        return False
    for token in tokens:
        stem = _entity_word_stem(token)
        if _entity_atom_is_generic(stem):
            continue
        compound_parts = re.findall(r"[A-Za-z0-9]+", stem)
        if len(compound_parts) > 1 and all(
            _entity_atom_is_generic(part) for part in compound_parts
        ):
            continue
        return False
    return True


def _looks_distinctive_proper_name(value: str) -> bool:
    """Recognize brand-like casing while exempting technical vocabulary."""

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'’./-]*", value)
    for word in words:
        stem = _entity_word_stem(word)
        if _entity_token_is_technical(stem):
            continue
        letters = re.sub(r"[^A-Za-z]+", "", stem)
        if len(letters) >= 3 and letters.isupper():
            return True
        if re.search(r"[a-z][A-Z]", stem) is not None:
            return True
    for match in _TITLECASE_PRODUCT_ENTITY.finditer(value):
        brand = _entity_word_stem(match.group("brand"))
        if not _entity_phrase_is_generic(brand):
            return True
    return False


def _contains_unsafe_faq_context(*values: Any) -> bool:
    context = " ".join(str(value or "") for value in values)
    return _contains_third_party_brand(context) or _looks_distinctive_proper_name(
        context
    )


def _comparison_operands(value: str, match: re.Match[str]) -> tuple[str, str]:
    # Comparison questions often put their interrogative predicate before a
    # comma/colon ("Which lasts longer, X vs Y?").  The final clause before
    # ``vs`` is the operand; earlier clauses are grammatical scaffolding.
    left = re.split(r"[,;:]", value[: match.start()])[-1].strip(" -|:,;")
    right = value[match.end() :].strip(" -|:,;")
    trailing_context = _COMPARISON_TRAILING_CONTEXT.search(right)
    if trailing_context is not None:
        right = right[: trailing_context.start()]
    return left, right.strip(" -|:,;.?!？")


def _looks_like_third_party_brand_question(value: str) -> bool:
    if _contains_third_party_brand(value) or _BRAND_QUALITY_QUESTION.search(value):
        return True
    # Distinctive internal capitals are a useful low-cost brand signal anywhere
    # in the question.  Plain Title Case and all-caps technical terms (PTFE,
    # LPG, CO2, and similar) are intentionally not treated as entities.
    if _looks_distinctive_proper_name(value):
        return True
    proper_name_match = _IS_PROPER_NAME_QUESTION.search(value)
    if proper_name_match is not None and not _entity_phrase_is_generic(
        proper_name_match.group("brand")
    ):
        return True
    for match in _VS_COMPARISON.finditer(value):
        left, right = _comparison_operands(value, match)
        if not (
            _comparison_side_is_generic(left)
            and _comparison_side_is_generic(right)
        ):
            return True
    review_match = _PROPER_NAME_REVIEW.search(value)
    if review_match is not None and not _entity_phrase_is_generic(
        review_match.group("brand")
    ):
        return True
    return False


def is_faq_question_candidate(value: Any) -> bool:
    """Return whether search text is a buyer question safe to publish.

    Search result titles are untrusted input.  Requiring both interrogative
    grammar and terminal question punctuation rejects listicles/search titles;
    the brand checks keep competitor entities out of research and provide a
    reusable guard for persisted research and generated FAQ.
    """

    question = _clean_text(value, limit=512).strip(" -|:")
    return bool(
        question
        and _QUESTION_START.match(question)
        and _QUESTION_END.search(question)
        and not _ARTICLE_OR_LISTICLE_TITLE.search(question)
        and not _MALFUNCTION_QUESTION.search(question)
        and not _looks_like_third_party_brand_question(question)
    )


def is_faq_text_brand_safe(value: Any) -> bool:
    """Return whether buyer-visible FAQ text contains no third-party entity."""

    return not _contains_unsafe_faq_context(value)


def is_specification_paraphrase_question(value: Any) -> bool:
    """Return whether a question would be rejected as a basic-spec restatement."""

    question = _clean_text(value, limit=512)
    return bool(
        _SPEC_PARAPHRASE.match(question) or _SPEC_PARAPHRASE_ZH.match(question)
    )


def sanitize_faq_research(research: Any) -> dict[str, Any]:
    """Project untrusted/current FAQ research into a safe, consistent snapshot.

    IDs and provenance of retained sources remain unchanged.  Derived clusters
    and quality counters are rebuilt so legacy persisted research cannot carry
    a removed competitor source into model input through stale metadata.
    """

    source_research = research if isinstance(research, dict) else {}
    raw_sources = source_research.get("sources")
    retained_sources: list[dict[str, Any]] = []
    retained_ids: set[str] = set()
    allowed_source_types = {
        "people_also_ask",
        "forum_question",
        "review_pain_point",
        "organic_question",
    }
    for raw_source in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(raw_source, dict):
            continue
        source_id = _clean_text(raw_source.get("id"), limit=200)
        question = _clean_text(raw_source.get("question"), limit=512)
        snippet = _clean_text(raw_source.get("snippet"))
        source_url = _clean_text(
            raw_source.get("source_url") or raw_source.get("url"),
            limit=2048,
        )
        query = _clean_text(raw_source.get("query"), limit=512)
        if (
            not source_id
            or source_id in retained_ids
            or not is_faq_question_candidate(question)
            or _contains_unsafe_faq_context(
                source_id,
                snippet,
                source_url,
                query,
            )
        ):
            continue
        source_type = _clean_text(raw_source.get("source_type"), limit=64)
        if source_type and source_type not in allowed_source_types:
            # Missing source_type is tolerated for legacy research.  An
            # explicit unknown type is untrusted provenance, not legacy data.
            continue

        raw_cluster = _clean_text(raw_source.get("intent_cluster"), limit=64)
        cluster = raw_cluster
        if (
            not re.fullmatch(r"[a-z0-9_]{1,64}", cluster)
            or _contains_unsafe_faq_context(cluster)
        ):
            cluster = _intent_cluster(f"{question} {snippet}")
        safe_source: dict[str, Any] = {
            "id": source_id,
            "question": question,
            "intent_cluster": cluster,
        }
        if source_type in allowed_source_types:
            safe_source["source_type"] = source_type
        if source_url:
            safe_source["source_url"] = source_url
        if snippet:
            safe_source["snippet"] = snippet
        if query:
            safe_source["query"] = query
        raw_rank = raw_source.get("rank")
        if not isinstance(raw_rank, bool):
            try:
                rank = max(1, int(raw_rank))
            except (TypeError, ValueError):
                rank = None
            if rank is not None:
                safe_source["rank"] = rank
        retained_ids.add(source_id)
        retained_sources.append(safe_source)

    # Raw cluster maps are derived, stale metadata.  Rebuild exclusively from
    # each retained source's validated/fallback intent cluster.
    clusters: dict[str, list[str]] = {}
    for source in retained_sources:
        clusters.setdefault(str(source["intent_cluster"]), []).append(
            str(source["id"])
        )

    strong_ids = {
        str(source["id"]).strip()
        for source in retained_sources
        if (
            not str(source.get("source_type") or "").strip()
            or str(source.get("source_type") or "").strip()
            in allowed_source_types
        )
        and not is_specification_paraphrase_question(source.get("question"))
    }
    strong_clusters = {
        cluster
        for cluster, source_ids in clusters.items()
        if any(source_id in strong_ids for source_id in source_ids)
    }
    quality_ready = len(strong_ids) >= 2 and len(strong_clusters) >= 2

    # Closed top-level projection: do not forward arbitrary provider response
    # objects that may contain unreviewed competitor entities.
    output: dict[str, Any] = {}
    raw_queries = source_research.get("queries")
    if isinstance(raw_queries, list):
        output["queries"] = [
            clean_query
            for query in raw_queries
            if (clean_query := _clean_text(query, limit=512))
            if not _contains_unsafe_faq_context(query)
        ]
    for field, limit in (("provider", 100), ("research_run_id", 100)):
        value = _clean_text(source_research.get(field), limit=limit)
        if value and not _contains_unsafe_faq_context(value):
            output[field] = value
    original_status = str(source_research.get("status") or "").strip()
    output.update(
        {
            "status": (
                "completed"
                if quality_ready
                else original_status
                if original_status in {"failed", "not_applicable"}
                else "insufficient"
            ),
            "sources": retained_sources,
            "clusters": clusters,
            "source_count": len(retained_sources),
            "quality_ready": quality_ready,
            "intent_cluster_count": len(strong_clusters),
        }
    )
    return output


def _question_id(source_type: str, question: str, url: str) -> str:
    digest = hashlib.sha1(
        f"{source_type}\n{_question_key(question)}\n{url}".encode("utf-8")
    ).hexdigest()[:12]
    return f"faq-src-{digest}"


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").casefold()
    except ValueError:
        return ""


def _intent_cluster(text: str) -> str:
    value = text.casefold()
    clusters = (
        ("safety", ("safe", "indoor", "carbon monoxide", "hazard", "fire")),
        ("travel_logistics", ("tsa", "flight", "plane", "airport", "check in", "carry on")),
        ("altitude_performance", ("altitude", "elevation", "high mountain")),
        ("cold_weather", ("cold", "winter", "low temperature", "freezing")),
        ("wind_weather", ("wind", "gust")),
        ("wet_weather", ("rain", "wet weather")),
        ("compatibility", ("compatible", "fit", "fuel", "canister", "battery", "replacement")),
        ("maintenance", ("clean", "maintain", "repair", "store", "rust")),
        ("operation", ("ignite", "start", "use", "install", "work", "cook")),
    )
    for cluster, terms in clusters:
        if any(term in value for term in terms):
            return cluster
    return "buyer_concern"


def _append_source(
    sources: list[dict[str, Any]],
    seen: set[str],
    *,
    question: Any,
    source_type: str,
    query: str,
    rank: int,
    url: Any = None,
    snippet: Any = None,
) -> None:
    text = _clean_text(question, limit=512).strip(" -|:")
    key = _question_key(text)
    clean_url = _clean_text(url, limit=2048)
    clean_snippet = _clean_text(snippet)
    if (
        not is_faq_question_candidate(text)
        or _contains_unsafe_faq_context(clean_snippet, clean_url, query)
        or len(key.split()) < 3
        or key in seen
    ):
        return
    # Only a fully safe source may claim the dedupe key.  This lets a lower-
    # priority forum/organic duplicate survive when a PAA item's context leaks
    # a competitor even though its question text itself looks harmless.
    seen.add(key)
    sources.append(
        {
            "id": _question_id(source_type, text, clean_url),
            "question": text,
            "source_type": source_type,
            "source_url": clean_url or None,
            "snippet": clean_snippet,
            "query": query,
            "rank": max(1, rank),
            "intent_cluster": _intent_cluster(f"{text} {snippet or ''}"),
        }
    )


def build_faq_research(
    responses: list[dict[str, Any]],
    *,
    queries: list[str],
) -> dict[str, Any]:
    """Flatten Serper PAA and question/pain-point organic results with provenance."""

    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Traverse every PAA response first.  This makes provenance priority global
    # (not merely per response) and ensures a duplicate organic result can never
    # displace the stronger PAA source.
    for response_index, response in enumerate(responses):
        if not isinstance(response, dict):
            continue
        query = queries[response_index] if response_index < len(queries) else ""
        paa = (
            response.get("peopleAlsoAsk")
            or response.get("people_also_ask")
            or response.get("relatedQuestions")
            or []
        )
        if isinstance(paa, list):
            for rank, item in enumerate(paa, start=1):
                if not isinstance(item, dict):
                    continue
                _append_source(
                    sources,
                    seen,
                    question=item.get("question") or item.get("title"),
                    source_type="people_also_ask",
                    query=query,
                    rank=rank,
                    url=item.get("link") or item.get("url"),
                    snippet=item.get("snippet") or item.get("answer"),
                )

    ranked_organic: list[dict[str, Any]] = []
    for response_index, response in enumerate(responses):
        if not isinstance(response, dict):
            continue
        query = queries[response_index] if response_index < len(queries) else ""
        organic = response.get("organic") or response.get("organic_results") or []
        if not isinstance(organic, list):
            continue
        for rank, item in enumerate(organic, start=1):
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title"), limit=512)
            snippet = _clean_text(item.get("snippet") or item.get("description"))
            url = _clean_text(item.get("link") or item.get("url"), limit=2048)
            domain = _domain(url)
            haystack = f"{title} {snippet}".casefold()
            is_forum = any(token in domain for token in _FORUM_DOMAINS)
            is_review = any(term in haystack for term in _REVIEW_TERMS)
            if not is_faq_question_candidate(title):
                continue
            source_type = (
                "forum_question"
                if is_forum
                else "review_pain_point" if is_review else "organic_question"
            )
            ranked_organic.append(
                {
                    "question": title,
                    "source_type": source_type,
                    "query": query,
                    "rank": rank,
                    "url": url,
                    "snippet": snippet,
                }
            )

    source_priority = {
        "forum_question": 0,
        "review_pain_point": 1,
        "organic_question": 2,
    }
    for candidate in sorted(
        ranked_organic,
        key=lambda item: source_priority[str(item["source_type"])],
    ):
        _append_source(
            sources,
            seen,
            question=candidate["question"],
            source_type=str(candidate["source_type"]),
            query=str(candidate["query"]),
            rank=int(candidate["rank"]),
            url=candidate["url"],
            snippet=candidate["snippet"],
        )

    clusters: dict[str, list[str]] = {}
    for source in sources:
        clusters.setdefault(source["intent_cluster"], []).append(source["id"])
    strong_sources = [
        source
        for source in sources
        if source["source_type"]
        in {"people_also_ask", "forum_question", "review_pain_point", "organic_question"}
        and not is_specification_paraphrase_question(source.get("question"))
    ]
    strong_clusters = {
        str(source.get("intent_cluster") or "buyer_concern")
        for source in strong_sources
    }
    quality_ready = len(strong_sources) >= 2 and len(strong_clusters) >= 2
    return sanitize_faq_research(
        {
            "status": "completed" if quality_ready else "insufficient",
            "queries": queries,
            "sources": sources[:50],
            "clusters": clusters,
            "source_count": len(sources),
            "quality_ready": quality_ready,
            "intent_cluster_count": len(strong_clusters),
        }
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 2
        and token
        not in {"the", "and", "for", "with", "this", "that", "from", "your"}
    }


def _matches_source(question: str, source_question: str) -> bool:
    left, right = _tokens(question), _tokens(source_question)
    if not left or not right:
        return False
    return len(left & right) / min(len(left), len(right)) >= 0.34


def _flatten_fact_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        output: list[str] = []
        for key, nested in value.items():
            if key not in {"source_url", "url"}:
                output.append(str(key))
            output.extend(_flatten_fact_text(nested))
        return output
    if isinstance(value, list):
        output: list[str] = []
        for nested in value:
            output.extend(_flatten_fact_text(nested))
        return output
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _canonical_number(value: str) -> str:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return value.replace(",", "")
    rendered = format(number.normalize(), "f")
    return "0" if rendered in {"-0", ""} else rendered


def evidence_number_tokens(value: Any) -> set[str]:
    """Return canonical decimal tokens without splitting decimal values."""

    if value is None or isinstance(value, bool):
        return set()
    return {
        _canonical_number(match.group(0))
        for match in _SPEC_NUMBER.finditer(str(value))
    }


def imperial_equivalent_number_tokens(value: Any, unit: Any) -> set[str]:
    """Project one verified metric value through the buyer-display converter."""

    converted = imperial_measurement(value, unit)
    if converted is not None:
        return evidence_number_tokens(converted[0])

    # Normalized specs occasionally retain a compound/raw string while keeping
    # the unit separately (for example ``17×17×12`` + ``cm``). Convert each
    # factual scalar through the same public converter and rounding path.
    output: set[str] = set()
    for token in evidence_number_tokens(value):
        scalar = imperial_measurement(token, unit)
        if scalar is not None:
            output.update(evidence_number_tokens(scalar[0]))
    return output


def structured_spec_number_tokens(structured_specs: Any) -> set[str]:
    """Collect only factual spec values plus their US buyer-display numbers.

    Identifiers, digests, labels, stable additional-spec keys, and translation
    bookkeeping are metadata even when they contain digits.  Restricting the
    source walk to explicit value fields prevents those digits from suppressing
    an otherwise supported FAQ answer.
    """

    output: set[str] = set()

    def collect_fact_value(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                collect_fact_value(nested)
            return
        if isinstance(value, list):
            for nested in value:
                collect_fact_value(nested)
            return
        if value is None or isinstance(value, bool):
            return
        output.update(evidence_number_tokens(value))

    def visit(value: Any, inherited_unit: Any = None) -> None:
        if isinstance(value, dict):
            unit = value.get("unit") or inherited_unit
            metric_value: Any = value.get("value")
            if metric_value in (None, "", [], {}):
                if value.get("min") is not None or value.get("max") is not None:
                    metric_value = {
                        "min": value.get("min"),
                        "max": value.get("max"),
                    }
                else:
                    metric_value = value.get("raw_value")
            if unit and metric_value not in (None, "", [], {}):
                output.update(
                    imperial_equivalent_number_tokens(metric_value, unit)
                )
            for nested_key, nested in value.items():
                key = str(nested_key).casefold()
                if key in _SPEC_METADATA_SUBTREE_KEYS:
                    continue
                if key in _SPEC_FACT_VALUE_KEYS:
                    collect_fact_value(nested)
                elif isinstance(nested, (dict, list)):
                    visit(nested, unit)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested, inherited_unit)

    visit(structured_specs or {})
    buyer_display = buyer_display_structured_specs(
        structured_specs,
        target_market="US",
    )
    for row in buyer_display.get("rows") or []:
        if isinstance(row, dict):
            collect_fact_value(row.get("display_value"))
    return output


def answer_spec_number_matches(answer: Any, structured_specs: Any) -> set[str]:
    answer_numbers = {
        _canonical_number(match.group(0))
        for match in _SPEC_NUMBER.finditer(str(answer or ""))
    }
    return answer_numbers & structured_spec_number_tokens(structured_specs)


def _answer_support_error(
    answer: str,
    *,
    cited_sources: list[dict[str, Any]],
    fact_corpus: str,
    structured_spec_numbers: set[str] | None = None,
) -> str | None:
    cited_snippets = " ".join(
        str(source.get("snippet") or "") for source in cited_sources
    ).casefold()
    support = f"{fact_corpus} {cited_snippets}".casefold()
    answer_numbers = {
        _canonical_number(match.group(0)) for match in _SPEC_NUMBER.finditer(answer)
    }
    repeated_spec_numbers = answer_numbers & (structured_spec_numbers or set())
    if repeated_spec_numbers:
        return "answer_repeats_product_specification_number"
    support_numbers = {
        _canonical_number(match.group(0)) for match in _SPEC_NUMBER.finditer(support)
    }
    if answer_numbers - support_numbers:
        return "answer_contains_unsupported_number"
    if _ABSOLUTE_SAFETY.search(answer) and not _ABSOLUTE_SAFETY.search(fact_corpus):
        return "unsupported_absolute_safety_claim"
    if _PRODUCT_ASSERTION.search(answer):
        answer_normalized = answer.casefold()
        for topic, terms in _ANSWER_CLAIM_TOPICS:
            if any(term in answer_normalized for term in terms) and not any(
                term in fact_corpus for term in terms
            ):
                return f"unsupported_product_claim:{topic}"
    return None


def validate_generated_faq(
    result: dict[str, Any],
    research: dict[str, Any] | None,
    *,
    approved_selling_points: list[dict[str, Any]] | None = None,
    structured_specs: dict[str, Any] | None = None,
    package_includes: list[str] | None = None,
) -> dict[str, Any]:
    """Drop fabricated/spec-parroting FAQ and stamp schema eligibility."""

    safe_result = result if isinstance(result, dict) else {}
    safe_research = research if isinstance(research, dict) else {}
    output = dict(safe_result)
    raw_research_sources = safe_research.get("sources")
    research_sources = [
        item
        for item in (
            raw_research_sources if isinstance(raw_research_sources, list) else []
        )
        if isinstance(item, dict)
        and item.get("id")
        and is_faq_question_candidate(item.get("question"))
    ]
    sources = {
        str(item.get("id")): item
        for item in research_sources
    }
    source_clusters: dict[str, set[str]] = {}
    raw_clusters = safe_research.get("clusters")
    clusters = raw_clusters if isinstance(raw_clusters, dict) else {}
    for cluster, source_ids in clusters.items():
        if not isinstance(source_ids, list):
            continue
        for source_id in source_ids:
            source_clusters.setdefault(str(source_id), set()).add(str(cluster))
    exact_sources: dict[str, list[dict[str, Any]]] = {}
    for source in research_sources:
        exact_sources.setdefault(
            _question_key(str(source.get("question") or "")), []
        ).append(source)

    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    fact_corpus = " ".join(
        [
            *_flatten_fact_text(approved_selling_points or []),
            *_flatten_fact_text(structured_specs or {}),
        ]
    ).casefold()
    structured_spec_numbers = structured_spec_number_tokens(structured_specs)
    if isinstance(package_includes, list) and package_includes:
        structured_spec_numbers.add(str(len(package_includes)))
    raw_items_value = safe_result.get("page_faq")
    raw_items = raw_items_value if isinstance(raw_items_value, list) else []
    evidence_autobind_count = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        raw = dict(raw)
        question = _clean_text(raw.get("question"), limit=512)
        answer = _clean_text(raw.get("answer"), limit=2000)
        raw_refs = raw.get("evidence_refs")
        malformed_refs = raw_refs is not None and (
            not isinstance(raw_refs, list)
            or any(not isinstance(ref, str) for ref in raw_refs)
        )
        provided_refs = [
            str(ref).strip()
            for ref in (raw_refs if isinstance(raw_refs, list) else [])
            if isinstance(ref, str)
            if str(ref).strip() in sources
        ]
        if not malformed_refs and not provided_refs:
            exact_matches = exact_sources.get(_question_key(question), [])
            if len(exact_matches) == 1:
                source = exact_matches[0]
                source_id = str(source.get("id"))
                source_cluster = str(source.get("intent_cluster") or "").strip()
                if not source_cluster:
                    cluster_matches = source_clusters.get(source_id, set())
                    if len(cluster_matches) == 1:
                        source_cluster = next(iter(cluster_matches))
                if source_cluster:
                    # Provider refs are advisory.  Missing/invalid refs can be
                    # repaired only by an exact normalized research-question
                    # match; paraphrases remain unbound and are dropped below.
                    raw["evidence_refs"] = [source_id]
                    raw["intent_cluster"] = source_cluster
                    evidence_autobind_count += 1
        refs = [
            str(ref).strip()
            for ref in (raw.get("evidence_refs") or [])
            if isinstance(ref, str)
            if str(ref).strip() in sources
        ] if not malformed_refs else []
        ref_clusters: set[str] = set()
        for ref in refs:
            source_cluster = str(sources[ref].get("intent_cluster") or "").strip()
            if source_cluster:
                ref_clusters.add(source_cluster)
            else:
                ref_clusters.update(source_clusters.get(ref, set()))
        resolved_cluster = (
            next(iter(ref_clusters))
            if len(ref_clusters) == 1
            else str(raw.get("intent_cluster") or "buyer_concern").strip()
            or "buyer_concern"
        )
        key = _question_key(question)
        reason = ""
        if not question or not answer:
            reason = "empty_question_or_answer"
        elif not is_faq_question_candidate(question):
            reason = "invalid_question_shape_or_third_party_brand"
        elif not is_faq_text_brand_safe(answer):
            reason = "third_party_brand_reference"
        elif malformed_refs:
            reason = "malformed_evidence_refs"
        elif key in seen:
            reason = "duplicate_question"
        elif is_specification_paraphrase_question(question):
            reason = "specification_paraphrase"
        elif not refs:
            reason = "missing_serper_evidence"
        elif not any(_matches_source(question, str(sources[ref].get("question") or "")) for ref in refs):
            reason = "question_does_not_match_evidence"
        elif len(ref_clusters) > 1:
            reason = "evidence_refs_cross_intent_clusters"
        elif any(
            _matches_source(question, accepted_item["question"])
            for accepted_item in accepted
            if str(accepted_item.get("intent_cluster") or "buyer_concern")
            == resolved_cluster
        ):
            reason = "duplicate_question_intent"
        else:
            reason = _answer_support_error(
                answer,
                cited_sources=[sources[ref] for ref in refs],
                fact_corpus=fact_corpus,
                structured_spec_numbers=structured_spec_numbers,
            ) or ""
        if reason:
            dropped.append({"question": question, "reason": reason})
            continue
        seen.add(key)
        accepted.append(
            {
                "question": question,
                "answer": answer,
                "evidence_refs": refs,
                "intent_cluster": resolved_cluster,
            }
        )

    accepted_clusters = {
        str(item.get("intent_cluster") or "buyer_concern") for item in accepted
    }
    eligible = (
        bool(safe_research.get("quality_ready"))
        and len(accepted) >= 2
        and len(accepted_clusters) >= 2
    )
    output["page_faq"] = accepted
    output["faq_quality"] = {
        "eligible_for_schema": eligible,
        "accepted_count": len(accepted),
        "dropped": dropped,
        "research_source_count": len(sources),
        "intent_cluster_count": len(accepted_clusters),
        "evidence_autobind_count": evidence_autobind_count,
        "reason": None if eligible else "insufficient_evidence_backed_questions",
    }
    return output


def faq_schema_is_eligible(marketing_copy_json: Any) -> bool:
    if not isinstance(marketing_copy_json, dict):
        return False
    quality = marketing_copy_json.get("faq_quality")
    return isinstance(quality, dict) and quality.get("eligible_for_schema") is True
