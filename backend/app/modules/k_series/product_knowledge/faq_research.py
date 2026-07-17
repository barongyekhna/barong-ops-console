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

from .buyer_display import buyer_display_structured_specs


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
    r"^(?:how|what|when|where|which|why|who|can|could|do|does|is|are|will|would|should)\b",
    re.IGNORECASE,
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
    if not text or len(key.split()) < 3 or key in seen:
        return
    seen.add(key)
    clean_url = _clean_text(url, limit=2048)
    sources.append(
        {
            "id": _question_id(source_type, text, clean_url),
            "question": text,
            "source_type": source_type,
            "source_url": clean_url or None,
            "snippet": _clean_text(snippet),
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
            is_question = bool("?" in title or _QUESTION_START.match(title))
            if not (is_forum or is_review or is_question):
                continue
            source_type = (
                "forum_question"
                if is_forum
                else "review_pain_point" if is_review else "organic_question"
            )
            _append_source(
                sources,
                seen,
                question=title,
                source_type=source_type,
                query=query,
                rank=rank,
                url=url,
                snippet=snippet,
            )

    clusters: dict[str, list[str]] = {}
    for source in sources:
        clusters.setdefault(source["intent_cluster"], []).append(source["id"])
    strong_sources = [
        source
        for source in sources
        if source["source_type"]
        in {"people_also_ask", "forum_question", "review_pain_point", "organic_question"}
    ]
    strong_clusters = {
        str(source.get("intent_cluster") or "buyer_concern")
        for source in strong_sources
    }
    quality_ready = len(strong_sources) >= 2 and len(strong_clusters) >= 2
    return {
        "status": "completed" if quality_ready else "insufficient",
        "queries": queries,
        "sources": sources[:50],
        "clusters": clusters,
        "source_count": len(sources),
        "quality_ready": quality_ready,
        "intent_cluster_count": len(strong_clusters),
    }


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
        output.update(_canonical_number(match.group(0)) for match in _SPEC_NUMBER.finditer(str(value)))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                key = str(nested_key).casefold()
                if key in _SPEC_METADATA_SUBTREE_KEYS:
                    continue
                if key in _SPEC_FACT_VALUE_KEYS:
                    collect_fact_value(nested)
                elif isinstance(nested, (dict, list)):
                    visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)

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

    output = dict(result)
    research_sources = [
        item
        for item in ((research or {}).get("sources") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    sources = {
        str(item.get("id")): item
        for item in research_sources
    }
    source_clusters: dict[str, set[str]] = {}
    raw_clusters = (research or {}).get("clusters")
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
    raw_items = result.get("page_faq") if isinstance(result, dict) else None
    evidence_autobind_count = 0
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        raw = dict(raw)
        question = _clean_text(raw.get("question"), limit=512)
        answer = _clean_text(raw.get("answer"), limit=2000)
        provided_refs = [
            str(ref).strip()
            for ref in (raw.get("evidence_refs") or [])
            if str(ref).strip() in sources
        ]
        if not provided_refs:
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
            if str(ref).strip() in sources
        ]
        key = _question_key(question)
        reason = ""
        if not question or not answer:
            reason = "empty_question_or_answer"
        elif key in seen:
            reason = "duplicate_question"
        elif _SPEC_PARAPHRASE.match(question) or _SPEC_PARAPHRASE_ZH.match(question):
            reason = "specification_paraphrase"
        elif not refs:
            reason = "missing_serper_evidence"
        elif not any(_matches_source(question, str(sources[ref].get("question") or "")) for ref in refs):
            reason = "question_does_not_match_evidence"
        elif any(
            _matches_source(question, accepted_item["question"])
            for accepted_item in accepted
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
                "intent_cluster": raw.get("intent_cluster")
                or sources[refs[0]].get("intent_cluster")
                or "buyer_concern",
            }
        )

    accepted_clusters = {
        str(item.get("intent_cluster") or "buyer_concern") for item in accepted
    }
    eligible = (
        bool((research or {}).get("quality_ready"))
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
