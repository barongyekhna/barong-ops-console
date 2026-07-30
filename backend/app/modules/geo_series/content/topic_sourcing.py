"""Topic sourcing for GEO clusters — real buyer-demand questions, not AI-invented.

M1 let the AI invent article topics from the product name ("garbage topic" risk).
This grounds topic selection in two datasets that are already Serper-mined and in
the DB (reuse-only, zero new Serper spend):

- K's per-product ``faq_research_json.sources[]`` (PAA / forum / organic questions);
- F's per-category ``f_category_keywords`` (related / PAA / organic-title phrases).

Every candidate is filtered + scored with K's tested predicates so malfunction,
spec-restatement, non-question, and third-party-brand items never reach the
operator. The operator picks; the picks become the engine's required question set.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...f_series.enrichment.models import FCategoryKeyword
from ...k_series.product_knowledge.faq_research import (
    _intent_cluster,
    is_faq_question_candidate,
    is_faq_text_brand_safe,
    is_specification_paraphrase_question,
)
from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import (
    KScopeContext,
    apply_scope_filters,
)
from .models import GeoContentCluster

# AI answer engines cite question-shaped demand; weight the sources by how
# reliably each represents a real buyer question.
_SOURCE_TYPE_WEIGHT = {
    "people_also_ask": 100,
    "forum_question": 80,
    "review_pain_point": 70,
    "organic_question": 60,
}
# Intent shapes AI loves to synthesize (how-to / compatibility / logistics) rank
# above vague "buyer_concern". Labels come from faq_research._intent_cluster.
_INTENT_BONUS = {
    "compatibility": 25,
    "operation": 20,
    "travel_logistics": 20,
    "maintenance": 15,
    "safety": 15,
    "wet_weather": 10,
    "cold_weather": 10,
    "wind_weather": 10,
    "altitude_performance": 10,
    "buyer_concern": 5,
}
_F_KEYWORD_TYPE_TO_SOURCE = {
    "people_also_ask": "people_also_ask",
    "organic_title": "organic_question",
    "related": "organic_question",
}


def _norm(question: Any) -> str:
    return re.sub(r"\s+", " ", str(question or "")).strip().lower().rstrip("?").strip()


def _rank_bonus(rank: Any) -> int:
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return 0
    return max(0, 20 - max(0, r - 1) * 2)


def _score(source_type: str, intent: str, rank: Any) -> int:
    return (
        _SOURCE_TYPE_WEIGHT.get(source_type, 50)
        + _INTENT_BONUS.get(intent, 0)
        + _rank_bonus(rank)
    )


def _accept(question: str) -> bool:
    """The clean-buyer-question gate: real question, brand-safe, not a spec restatement."""
    return bool(
        question
        and is_faq_question_candidate(question)
        and is_faq_text_brand_safe(question)
        and not is_specification_paraphrase_question(question)
    )


def _products_for_cluster(
    db: Session, cluster: GeoContentCluster, scope_context: KScopeContext
) -> list[KProductKnowledgeProduct]:
    if cluster.seed_product_id is not None:
        product = db.get(KProductKnowledgeProduct, cluster.seed_product_id)
        if product is not None:
            return [product]
    if not cluster.google_category_id:
        return []
    query = apply_scope_filters(
        select(KProductKnowledgeProduct).where(
            KProductKnowledgeProduct.google_product_category
            == cluster.google_category_id
        ),
        KProductKnowledgeProduct,
        scope_context,
    )
    return list(db.execute(query).scalars().all())


def _k_candidates(products: list[KProductKnowledgeProduct]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for product in products:
        research = getattr(product, "faq_research_json", None)
        if not isinstance(research, dict):
            continue
        for source in research.get("sources") or []:
            if not isinstance(source, dict):
                continue
            question = str(source.get("question") or "").strip()
            if not _accept(question):
                continue
            intent = str(source.get("intent_cluster") or "").strip() or _intent_cluster(
                question
            )
            source_type = str(source.get("source_type") or "organic_question").strip()
            out.append(
                {
                    "question": question,
                    "source": "k_faq",
                    "source_type": source_type,
                    "intent": intent,
                    "rank": source.get("rank"),
                    "snippet": str(source.get("snippet") or "")[:280] or None,
                    "score": _score(source_type, intent, source.get("rank")),
                }
            )
    return out


def _f_candidates(
    db: Session, cluster: GeoContentCluster
) -> list[dict[str, Any]]:
    if not cluster.google_category_id:
        return []
    rows = db.execute(
        select(FCategoryKeyword).where(
            FCategoryKeyword.category_id == cluster.google_category_id,
            FCategoryKeyword.status.in_(("candidate", "approved")),
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        question = str(row.keyword_text or "").strip()
        if not _accept(question):
            continue
        source_type = _F_KEYWORD_TYPE_TO_SOURCE.get(
            row.keyword_type, "organic_question"
        )
        intent = _intent_cluster(question)
        out.append(
            {
                "question": question,
                "source": "f_keyword",
                "source_type": source_type,
                "intent": intent,
                "rank": row.rank,
                "snippet": None,
                "score": _score(source_type, intent, row.rank),
            }
        )
    return out


def list_topic_candidates(
    db: Session, *, cluster: GeoContentCluster, scope_context: KScopeContext
) -> list[dict[str, Any]]:
    """Ranked, de-duplicated, clean buyer-question candidates for a cluster.

    Reuse-only: reads existing K faq_research + F keywords; no new network calls.
    """
    products = _products_for_cluster(db, cluster, scope_context)
    raw = _k_candidates(products) + _f_candidates(db, cluster)
    # 类目级深挖出来的问句(花钱抓的,已落表)也一并合进来。它们和上面两个来源
    # 同形,去重按归一化问句走,所以同一个问句从哪来都只会出现一次。
    try:
        from .topic_mining import mined_candidates

        raw += mined_candidates(db, cluster_id=cluster.id)
    except Exception:  # noqa: BLE001 - 深挖表缺席不该让候选列表崩
        pass

    best: dict[str, dict[str, Any]] = {}
    for candidate in raw:
        key = _norm(candidate["question"])
        if not key:
            continue
        existing = best.get(key)
        if existing is None or candidate["score"] > existing["score"]:
            best[key] = candidate
    return sorted(best.values(), key=lambda c: c["score"], reverse=True)


__all__ = ["list_topic_candidates"]
