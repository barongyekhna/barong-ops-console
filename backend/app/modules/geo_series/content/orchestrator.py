"""GeoContentOrchestrator — turn K product facts into AI-citable cluster content.

Decoupled from K's worker, but reuses K's building blocks:
- reads verified facts off ``KProductKnowledgeProduct`` (buyer-display specs,
  approved selling points, package includes, keywords);
- borrows K's module gate / key binding for the AI call (module_id
  ``k.product_knowledge``) — GEO is the same 独立站 pipeline drawing on K data, so
  it shares K's provider key instead of requiring a separate binding;
- guards output with the brand blacklist + CJK + numeric-grounding checks.

Machine writes, operator reviews: content lands in ``geo_content_items`` for
review; nothing is published (publishing is milestone 2, a dedicated n8n flow).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    normalized_brand_terms,
    sanitize_snapshot_for_generation,
)
from ...k_series.product_knowledge.buyer_display import (
    buyer_display_structured_specs,
)
from ...k_series.product_knowledge.category_resolver import google_category_path
from ...k_series.product_knowledge.evidence_guard import canonical_package_includes
from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .analysis import attach_analysis_safely
from .constants import ITEM_TYPES, REPEATABLE_ITEM_TYPES
from ...content_core.fact_sufficiency import (
    fact_blockers,
    fact_warnings,
    product_fact_report,
)
from ...content_core.guards import audit_content_item, evidence_number_corpus
from .models import GeoContentCluster, GeoContentItem
from .prompt_skills import (
    GEO_CONTENT_SKILL_VERSION,
    geo_content_instruction,
    geo_product_spotlight_instruction,
    geo_revise_instruction,
)

logger = logging.getLogger(__name__)

_PROVIDER = "chatgpt"


class GeoContentError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class GeoContentOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- public entry ----------------------------------------------------------
    def generate_cluster(
        self,
        *,
        cluster_id: UUID,
        scope_context: KScopeContext,
        user: Any | None,
    ) -> GeoContentCluster:
        cluster = self._require_cluster(cluster_id, scope_context)
        products = self._products_for_cluster(cluster, scope_context)
        if not products:
            raise GeoContentError(
                "GEO_CLUSTER_HAS_NO_PRODUCTS",
                "This cluster has no source products to draw facts from.",
                status_code=409,
            )

        cluster.status = "generating"
        self.db.flush()

        forbidden_terms = sorted(
            {term for product in products for term in normalized_brand_terms(product)}
        )
        evidence_numbers: set[str] = set()
        payload_products: list[dict[str, Any]] = []
        fact_reports: list[dict[str, Any]] = []
        for product in products:
            facts, numbers = self._product_facts(product)
            payload_products.append(facts)
            evidence_numbers |= numbers
            fact_reports.append(product_fact_report(facts, numbers))

        # 工艺事实与产品规格并列进接地语料——写「30 分钟浸泡测试」才不会被护栏
        # 当成编造。护栏一行都不用改:evidence_number_corpus 本就是变参。
        craft_rows, craft_payload, craft_numbers = self._craft_facts(products)
        evidence_numbers |= craft_numbers

        # Nothing verifiable to say → do not write. The grounding rule stops the
        # model inventing, but not from writing fluent emptiness, and emptiness is
        # what no output guard can catch. Refuse, and name what to go fill in.
        for note in fact_warnings(fact_reports):
            logger.warning("GEO cluster %s: %s", cluster.id, note)
        thin = fact_blockers(fact_reports)
        if thin:
            cluster.status = "draft"
            self.db.flush()
            raise GeoContentError(
                "GEO_INSUFFICIENT_FACTS",
                "事实不足，拒绝生成（宁可不写，也不写正确的废话）：\n" + "\n".join(thin),
                status_code=409,
            )

        category_path = self._category_path_text(cluster)
        # Operator-picked real buyer questions become the server-owned required set.
        # Empty → graceful fallback to product-derived generation (M1 behaviour).
        required_questions = _required_questions(cluster.picked_questions_json)
        picked_norm = {_norm_question(q["question"]) for q in required_questions}

        # Generation is INCREMENTAL: content the operator already approved survives
        # a re-run, so writing those topics again would duplicate them inside one
        # cluster (two hubs, the same question answered twice) — the exact
        # self-competition this module exists to avoid. Write only what is missing.
        kept = self._kept_items(cluster.id)
        covered_questions = _covered_questions(kept)
        skip_item_types = sorted(
            {i.item_type for i in kept if i.item_type not in REPEATABLE_ITEM_TYPES}
        )
        pending_questions = [
            q
            for q in required_questions
            if _norm_question(q["question"]) not in covered_questions
        ]
        if kept and not pending_questions and required_questions:
            unwritten_types = [t for t in ITEM_TYPES if t not in skip_item_types]
            # Repeatable types are always "unwritten", so they only count as work
            # when there is actually a pending question to hang one on.
            if not unwritten_types or set(unwritten_types) <= REPEATABLE_ITEM_TYPES:
                cluster.status = "needs_review"
                self.db.flush()
                raise GeoContentError(
                    "GEO_NOTHING_TO_GENERATE",
                    "选中的话题都已经有对应内容了（已批准的内容不会被重写）。"
                    "想改已有内容请用「按批评重写」，或先驳回再重新生成。",
                    status_code=409,
                )

        ai_input = {
            "task": "geo_content_generation",
            "instruction": geo_content_instruction(),
            "topic": cluster.topic or cluster.title,
            "category_path": category_path,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": forbidden_terms,
            "products": payload_products,
            # 自有工厂的工艺事实:竞品抄不走的那部分内容。
            "craft_facts": craft_payload,
            "required_questions": pending_questions or required_questions,
            # Already-approved pieces stay; do not produce these types again.
            "skip_item_types": skip_item_types,
            # The server does the subtraction. Listing every type and asking the
            # model to subtract `skip_item_types` made it go off-contract entirely
            # once only one type was left (2026-07-29: it invented an item_type and
            # a response shape of its own). Tell it exactly what to write.
            "produce_item_types": [
                t
                for t in ITEM_TYPES
                if t not in skip_item_types and t != "product_spotlight"
            ],
            # So the new pieces complement the kept ones instead of repeating them.
            "existing_content": [
                {"item_type": i.item_type, "title": i.title} for i in kept
            ],
        }

        # Release the read transaction before the long AI call (idle-in-txn rule).
        self.db.commit()

        result = self._call_ai(ai_input, user)
        raw_items = result.get("content_items") if isinstance(result, dict) else None
        if not isinstance(raw_items, list) or not raw_items:
            raise GeoContentError(
                "GEO_CONTENT_SCHEMA_INVALID",
                "Content provider returned no usable content_items.",
                status_code=502,
            )

        self._replace_items(
            cluster_id=cluster.id,
            scope_context=scope_context,
            raw_items=raw_items,
            forbidden_terms=forbidden_terms,
            evidence_numbers=evidence_numbers,
            picked_norm=picked_norm,
            skip_item_types=set(skip_item_types),
            covered_questions=covered_questions,
            user=user,
            # 问句自带的数字("5 gallon")是题目给的,不是编的——算式里可以用。
            context_numbers=_numbers_in_questions(required_questions),
        )

        self._record_craft_usage(cluster_id, craft_rows)

        cluster = self._require_cluster(cluster_id, scope_context)
        cluster.status = "needs_review"
        # The freshly generated content covers every attached product, so the
        # "new products since last generation" hint is resolved.
        cluster.pending_product_ids_json = []
        self.db.flush()

        # Reading aid for review: DeepSeek-flash explains each new piece. Runs
        # after the content is safely persisted and never blocks it.
        fresh = self.db.execute(
            select(GeoContentItem).where(
                GeoContentItem.cluster_id == cluster.id,
                GeoContentItem.analysis_json.is_(None),
            )
        ).scalars().all()
        attach_analysis_safely(
            self.db, list(fresh), topic=cluster.topic or cluster.title, user=user
        )
        return cluster

    def generate_product_spotlight(
        self,
        *,
        cluster_id: UUID,
        product_id: UUID,
        scope_context: KScopeContext,
        user: Any | None,
    ) -> GeoContentItem:
        """Add ONE article for a differentiated product inside a shared cluster.

        Opt-in (the operator decides): same-category products share a cluster, and
        only a genuinely distinct one earns its own piece. Replaces that product's
        existing spotlight, if any; never touches the cluster's other content.
        """
        cluster = self._require_cluster(cluster_id, scope_context)
        product = self.db.get(KProductKnowledgeProduct, product_id)
        if product is None:
            raise GeoContentError(
                "GEO_PRODUCT_NOT_FOUND", "Product not found.", status_code=404
            )
        siblings = [
            p
            for p in self._products_for_cluster(cluster, scope_context)
            if p.id != product.id
        ]

        facts, evidence_numbers = self._product_facts(product)
        sibling_facts: list[dict[str, Any]] = []
        for sibling in siblings:
            s_facts, s_numbers = self._product_facts(sibling)
            sibling_facts.append(s_facts)
            evidence_numbers |= s_numbers
        forbidden_terms = sorted(
            {
                term
                for p in [product, *siblings]
                for term in normalized_brand_terms(p)
            }
        )

        ai_input = {
            "task": "geo_product_spotlight",
            "instruction": geo_product_spotlight_instruction(),
            "topic": cluster.topic or cluster.title,
            "category_path": self._category_path_text(cluster),
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": forbidden_terms,
            "product": facts,
            "sibling_products": sibling_facts,
        }
        # Release the read transaction before the long AI call (idle-in-txn rule).
        self.db.commit()

        result = self._call_ai(ai_input, user)
        raw_items = result.get("content_items") if isinstance(result, dict) else None
        if not isinstance(raw_items, list) or not raw_items:
            raise GeoContentError(
                "GEO_CONTENT_SCHEMA_INVALID",
                "Spotlight provider returned no usable content_items.",
                status_code=502,
            )
        raw = next((item for item in raw_items if isinstance(item, dict)), None)
        if raw is None:
            raise GeoContentError(
                "GEO_CONTENT_SCHEMA_INVALID",
                "Spotlight provider returned no usable content_items.",
                status_code=502,
            )

        audit = audit_content_item(
            raw,
            forbidden_terms=forbidden_terms,
            evidence_numbers=evidence_numbers,
        )
        # One spotlight per product: replace this product's previous one only.
        product_key = str(product.id)
        existing = self.db.execute(
            select(GeoContentItem).where(
                GeoContentItem.cluster_id == cluster.id,
                GeoContentItem.item_type == "product_spotlight",
            )
        ).scalars().all()
        for item in existing:
            refs = item.source_product_ids_json
            if isinstance(refs, list) and product_key in [str(r) for r in refs]:
                self.db.delete(item)

        spotlight = GeoContentItem(
            cluster_id=cluster.id,
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
            item_type="product_spotlight",
            title=str(raw.get("title") or "").strip()[:512] or "Untitled",
            body_json={
                "sections": raw.get("sections") or [],
                "answer_blocks": raw.get("answer_blocks") or [],
            },
            seo_json=raw.get("seo") if isinstance(raw.get("seo"), dict) else None,
            # Server-owned: this piece belongs to this product, whatever the model wrote.
            source_product_ids_json=[product_key],
            schema_type="Article",
            brand_audit_json=audit,
            generation_status="generated",
            skill_version=GEO_CONTENT_SKILL_VERSION,
            provider=_PROVIDER,
            created_by_user_id=getattr(user, "id", None),
        )
        self.db.add(spotlight)
        # This product is now written about; drop it from the pending hint.
        pending = cluster.pending_product_ids_json
        if isinstance(pending, list):
            cluster.pending_product_ids_json = [
                p for p in pending if str(p) != product_key
            ]
        self.db.flush()
        attach_analysis_safely(
            self.db, [spotlight], topic=cluster.topic or cluster.title, user=user
        )
        return spotlight

    def revise_item(
        self,
        *,
        item_id: UUID,
        scope_context: KScopeContext,
        user: Any | None,
    ) -> GeoContentItem:
        """Rewrite one piece against its review critique, without inventing facts.

        Critiques the product data cannot support are reported back rather than
        faked — those become the data gaps to fill in K.
        """
        item = self.db.execute(
            apply_scope_filters(
                select(GeoContentItem).where(GeoContentItem.id == item_id),
                GeoContentItem,
                scope_context,
            )
        ).scalar_one_or_none()
        if item is None:
            raise GeoContentError(
                "GEO_ITEM_NOT_FOUND", "Content item not found.", status_code=404
            )
        analysis = item.analysis_json if isinstance(item.analysis_json, dict) else {}
        risks = [str(r) for r in (analysis.get("risks") or []) if str(r).strip()]
        if not risks:
            raise GeoContentError(
                "GEO_NO_CRITIQUE",
                "这篇还没有可用的批评意见——先生成 AI 解读。",
                status_code=409,
            )

        cluster = self._require_cluster(item.cluster_id, scope_context)
        products = self._products_for_cluster(cluster, scope_context)
        evidence_numbers: set[str] = set()
        payload_products: list[dict[str, Any]] = []
        for product in products:
            facts, numbers = self._product_facts(product)
            payload_products.append(facts)
            evidence_numbers |= numbers
        # 重写也要拿到工艺事实:否则同一段话在生成时合规、重写时反而被判无据。
        revise_craft_rows, revise_craft_payload, revise_craft_numbers = (
            self._craft_facts(products)
        )
        evidence_numbers |= revise_craft_numbers
        forbidden_terms = sorted(
            {term for product in products for term in normalized_brand_terms(product)}
        )
        body = item.body_json if isinstance(item.body_json, dict) else {}
        current = {
            "item_type": item.item_type,
            "title": item.title,
            "sections": body.get("sections") or [],
            "answer_blocks": body.get("answer_blocks") or [],
            "seo": item.seo_json if isinstance(item.seo_json, dict) else {},
        }
        round_no = 1
        if isinstance(item.revision_json, dict):
            try:
                round_no = int(item.revision_json.get("round") or 0) + 1
            except (TypeError, ValueError):
                round_no = 1

        ai_input = {
            "task": "geo_content_revision",
            "instruction": geo_revise_instruction(),
            "topic": cluster.topic or cluster.title,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": forbidden_terms,
            "current_content": current,
            "critiques": risks,
            "products": payload_products,
            "craft_facts": revise_craft_payload,
        }
        # Release the read transaction before the long AI call (idle-in-txn rule).
        self.db.commit()

        result = self._call_ai(ai_input, user)
        revised = result.get("item") if isinstance(result, dict) else None
        if not isinstance(revised, dict):
            raise GeoContentError(
                "GEO_CONTENT_SCHEMA_INVALID",
                "Revision provider returned no usable item.",
                status_code=502,
            )

        audit = audit_content_item(
            revised,
            forbidden_terms=forbidden_terms,
            evidence_numbers=evidence_numbers,
            context_numbers=_numbers_in_questions(
                [{"question": item.title}]
                + [
                    {"question": b.get("question")}
                    for b in (body.get("answer_blocks") or [])
                    if isinstance(b, dict)
                ]
            ),
        )
        item = self.db.execute(
            select(GeoContentItem).where(GeoContentItem.id == item_id)
        ).scalar_one()
        item.title = str(revised.get("title") or item.title).strip()[:512]
        item.body_json = {
            "sections": revised.get("sections") or [],
            "answer_blocks": revised.get("answer_blocks") or [],
        }
        if isinstance(revised.get("seo"), dict):
            new_seo = dict(revised["seo"])
            # 死规矩(2026-07-29 实地踩到): 已经发布过的文章,slug 锁死。
            # 重写时模型改了 seo.url_slug,发布流照着改了 WordPress 固定链接,
            # 线上网址当场失效。刚发布几小时还好,一篇有排名的文章这么改就是
            # 把积累的权重直接丢掉。内容可以重写,地址不行。
            if item.wp_post_id:
                old_slug = (item.seo_json or {}).get("url_slug") if isinstance(
                    item.seo_json, dict
                ) else None
                if old_slug:
                    new_seo["url_slug"] = old_slug
            item.seo_json = new_seo
        item.brand_audit_json = audit
        # A rewrite invalidates the previous approval — it must be re-reviewed.
        item.review_status = "pending"
        item.revision_json = {
            "round": round_no,
            "addressed": [
                str(a).strip()
                for a in (result.get("addressed") or [])
                if str(a).strip()
            ],
            "unaddressed": _clean_unaddressed(result.get("unaddressed")),
        }
        # The piece changed, so its old reading no longer describes it.
        item.analysis_json = None
        # 重写 = 重新引用一次,台账要记新版本,否则它会一直挂在需复核清单上。
        self._record_craft_usage_for(str(item.id), revise_craft_rows)
        self.db.flush()

        attach_analysis_safely(
            self.db, [item], topic=cluster.topic or cluster.title, user=user
        )
        return self.db.execute(
            select(GeoContentItem).where(GeoContentItem.id == item_id)
        ).scalar_one()

    def _kept_items(self, cluster_id: UUID) -> list[GeoContentItem]:
        """Items a re-run preserves: operator-approved pieces + product spotlights."""
        return list(
            self.db.execute(
                select(GeoContentItem).where(
                    GeoContentItem.cluster_id == cluster_id,
                    (GeoContentItem.review_status == "approved")
                    | (GeoContentItem.item_type == "product_spotlight"),
                )
            ).scalars().all()
        )

    # -- data loading ----------------------------------------------------------
    def _require_cluster(
        self, cluster_id: UUID, scope_context: KScopeContext
    ) -> GeoContentCluster:
        query = apply_scope_filters(
            select(GeoContentCluster).where(GeoContentCluster.id == cluster_id),
            GeoContentCluster,
            scope_context,
        )
        cluster = self.db.execute(query).scalar_one_or_none()
        if cluster is None:
            raise GeoContentError(
                "GEO_CLUSTER_NOT_FOUND", "Cluster not found.", status_code=404
            )
        return cluster

    def _products_for_cluster(
        self, cluster: GeoContentCluster, scope_context: KScopeContext
    ) -> list[KProductKnowledgeProduct]:
        """Every product this cluster covers.

        One cluster per category: the tracked product list wins (P attaches each
        published product to its category's cluster), falling back to the seed
        product, then to any scoped product in the category.
        """
        tracked = cluster.product_ids_json
        if isinstance(tracked, list) and tracked:
            products: list[KProductKnowledgeProduct] = []
            for raw in tracked:
                try:
                    product = self.db.get(KProductKnowledgeProduct, UUID(str(raw)))
                except (TypeError, ValueError):
                    continue
                if product is not None:
                    products.append(product)
            if products:
                return products
        if cluster.seed_product_id is not None:
            product = self.db.get(KProductKnowledgeProduct, cluster.seed_product_id)
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
        return list(self.db.execute(query).scalars().all())

    def _category_path_text(self, cluster: GeoContentCluster) -> str:
        if cluster.category_path:
            return cluster.category_path
        if cluster.google_category_id:
            try:
                path = google_category_path(self.db, cluster.google_category_id)
                return " > ".join(str(seg.get("name") or "") for seg in path)
            except Exception:  # noqa: BLE001 - path is a display nicety
                return ""
        return ""

    def _record_craft_usage(self, cluster_id: UUID, facts: list[Any]) -> None:
        """记下这一簇的内容引用了哪些工艺事实的**哪个版本**。

        我们不知道 AI 具体用了哪几条,所以按"喂进去的都算引用"记账。这会**多报**
        (给了但没用上的也进复核清单),不会**漏报**——而漏报才是危险的那一侧:
        工艺改了却没人知道哪篇文章跟着错了。
        """
        if not facts:
            return
        try:
            from ...content_core.facts.service import record_usage

            items = self.db.execute(
                select(GeoContentItem.id).where(
                    GeoContentItem.cluster_id == cluster_id
                )
            ).scalars().all()
            for item_id in items:
                record_usage(
                    self.db,
                    content_kind="geo_item",
                    content_id=str(item_id),
                    facts=facts,
                )
        except Exception:  # noqa: BLE001 - 台账记不上不该毁掉已生成的内容
            logger.exception("craft-fact usage ledger write failed")

    def _record_craft_usage_for(self, content_id: str, facts: list[Any]) -> None:
        """单篇版本,给重写用。"""
        if not facts:
            return
        try:
            from ...content_core.facts.service import record_usage

            record_usage(
                self.db,
                content_kind="geo_item",
                content_id=content_id,
                facts=facts,
            )
        except Exception:  # noqa: BLE001 - 同上,台账不该毁内容
            logger.exception("craft-fact usage ledger write failed")

    def _craft_facts(
        self, products: list[KProductKnowledgeProduct]
    ) -> tuple[list[Any], list[dict[str, Any]], set[str]]:
        """已批准的工艺事实 → (原始行, 给 AI 的载荷, 接地数字)。

        产品规格说的是"这台机器是什么",工艺事实说的是"我们怎么做出来的"——后者
        是自有工厂唯一说得出、竞品抄不走的内容,也是 GEO 指南里最难被质疑的部分。

        只取 ``approved``;未绑定产品的算通用工艺(整厂能力),绑定了的只给对应产品。
        取不到就当没有——工艺库为空绝不该拖垮生成。
        """
        try:
            from ...content_core.facts import service as craft

            identifiers = {str(p.id) for p in products}
            identifiers |= {
                str(getattr(p, "product_key", "") or "") for p in products
            }
            identifiers.discard("")
            rows = [
                fact
                for fact in craft.approved_facts(self.db)
                if not (fact.product_ids_json or [])
                or identifiers.intersection(
                    {str(x) for x in (fact.product_ids_json or [])}
                )
            ]
        except Exception:  # noqa: BLE001 - 工艺库是增益,不是生成的前置条件
            logger.exception("craft-fact lookup failed; generating without them")
            return [], [], set()

        payload = [
            {
                "topic": fact.topic,
                "claim": fact.claim,
                "detail": fact.detail,
                "value": fact.value,
                "unit": fact.unit,
            }
            for fact in rows
        ]
        from ...content_core.facts.service import grounding_texts

        return rows, payload, evidence_number_corpus(*grounding_texts(rows))

    def _product_facts(
        self, product: KProductKnowledgeProduct
    ) -> tuple[dict[str, Any], set[str]]:
        specs = buyer_display_structured_specs(product.structured_specs_json)
        selling_points = _approved_selling_point_texts(product)
        package_includes = canonical_package_includes(
            getattr(product, "package_includes_json", None),
            product.structured_specs_json,
        )
        snapshot = {
            "product_key": getattr(product, "product_key", None),
            "sku": getattr(product, "sku", None),
            "product_name": getattr(product, "product_name_en", None),
            "primary_keyword": getattr(product, "primary_keyword", None),
            "specs": specs,
            "selling_points": selling_points,
            "package_includes": package_includes,
        }
        # Strip any third-party brand from the snapshot before the AI sees it.
        safe = sanitize_snapshot_for_generation(snapshot, product)
        numbers = evidence_number_corpus(
            specs, selling_points, package_includes
        )
        return safe, numbers

    # -- AI call ---------------------------------------------------------------
    def _call_ai(self, payload: dict[str, Any], user: Any | None) -> dict[str, Any]:
        from ....db.session import SessionLocal
        from ....services.ai_provider_router import AIExecutionRouter
        from ...k_series.product_knowledge.constants import (
            MODULE_KEY as K_MODULE_KEY,
            TARGET_ORGANIZATION_NAME,
        )

        provider_db = SessionLocal()
        try:
            return AIExecutionRouter(provider_db).execute(
                provider=_PROVIDER,
                task_type="generate",
                payload=payload,
                org=TARGET_ORGANIZATION_NAME,
                module_id=K_MODULE_KEY,
                user=user,
            )
        finally:
            provider_db.close()

    # -- persistence -----------------------------------------------------------
    def _replace_items(
        self,
        *,
        cluster_id: UUID,
        scope_context: KScopeContext,
        raw_items: list[Any],
        forbidden_terms: list[str],
        evidence_numbers: set[str],
        picked_norm: set[str],
        skip_item_types: set[str],
        covered_questions: set[str],
        user: Any | None,
        context_numbers: set[str] | None = None,
    ) -> None:
        # Regeneration replaces the cluster's own draft pieces ONLY. Content the
        # operator already approved is theirs — it must never be silently deleted
        # by a re-run. Product spotlights are separately opted into per product and
        # are likewise out of scope here.
        self.db.execute(
            delete(GeoContentItem).where(
                GeoContentItem.cluster_id == cluster_id,
                GeoContentItem.review_status != "approved",
                GeoContentItem.item_type != "product_spotlight",
            )
        )
        user_id = getattr(user, "id", None)
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item_type = str(raw.get("item_type") or "").strip()
            if item_type not in ITEM_TYPES:
                item_type = "qa"
            # An approved piece already occupies this slot — do not duplicate it,
            # whatever the model chose to return.
            if item_type in skip_item_types:
                continue
            title = str(raw.get("title") or "").strip()[:512] or "Untitled"
            answer_blocks = raw.get("answer_blocks") or []
            # Enforce the server-owned question set: a qa block may only answer a
            # question the operator picked (K's _canonicalize_generated_faq analog).
            # When nothing was picked (fallback), keep the model's questions as-is.
            if item_type == "qa" and picked_norm:
                answer_blocks = [
                    block
                    for block in answer_blocks
                    if isinstance(block, dict)
                    and _norm_question(block.get("question")) in picked_norm
                    and _norm_question(block.get("question")) not in covered_questions
                ]
                raw = {**raw, "answer_blocks": answer_blocks}
            body_json = {
                "sections": raw.get("sections") or [],
                "answer_blocks": answer_blocks,
            }
            audit = audit_content_item(
                raw,
                forbidden_terms=forbidden_terms,
                evidence_numbers=evidence_numbers,
                context_numbers=context_numbers,
            )
            self.db.add(
                GeoContentItem(
                    cluster_id=cluster_id,
                    workspace_key=scope_context.workspace_key,
                    business_context=scope_context.business_context,
                    scope_mode=scope_context.scope_mode,
                    item_type=item_type,
                    title=title,
                    body_json=body_json,
                    seo_json=raw.get("seo") if isinstance(raw.get("seo"), dict) else None,
                    source_product_ids_json=raw.get("source_products") or [],
                    schema_type="FAQPage" if item_type == "qa" else "Article",
                    brand_audit_json=audit,
                    generation_status="generated",
                    skill_version=GEO_CONTENT_SKILL_VERSION,
                    provider=_PROVIDER,
                    created_by_user_id=user_id,
                )
            )
        self.db.flush()


def _numbers_in_questions(questions: Any) -> set[str]:
    """Numbers the questions themselves supply — given by the asker, not invented."""
    from ...content_core.guards import numbers_in_text

    out: set[str] = set()
    for entry in questions if isinstance(questions, list) else []:
        text = (
            entry.get("question") if isinstance(entry, dict) else entry
        )
        out |= numbers_in_text(str(text or ""))
    return out


def _covered_questions(kept_items: list[Any]) -> set[str]:
    """Questions the preserved pieces already answer — never write them twice."""
    covered: set[str] = set()
    for item in kept_items:
        body = item.body_json if isinstance(item.body_json, dict) else {}
        for block in body.get("answer_blocks") or []:
            if isinstance(block, dict):
                key = _norm_question(block.get("question"))
                if key:
                    covered.add(key)
    return covered


def _clean_unaddressed(raw: Any) -> list[dict[str, Any]]:
    """Critiques the rewrite refused to fake, with what data is missing."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw[:12]:
        if not isinstance(entry, dict):
            continue
        critique = str(entry.get("critique") or "").strip()
        if not critique:
            continue
        missing = str(entry.get("missing_fact") or "").strip()
        out.append(
            {
                "critique": critique[:500],
                "reason": str(entry.get("reason") or "").strip()[:500],
                "needs_data": bool(entry.get("needs_data")) or bool(missing),
                "missing_fact": missing[:200],
            }
        )
    return out


def _norm_question(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower().rstrip("?").strip()


def _required_questions(picked: Any) -> list[dict[str, str]]:
    """Project stored picks into the server-owned required set (deduped)."""
    if not isinstance(picked, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in picked:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        key = _norm_question(question)
        if not question or key in seen:
            continue
        seen.add(key)
        out.append(
            {"question": question, "intent": str(item.get("intent") or "").strip()}
        )
    return out


def _approved_selling_point_texts(product: KProductKnowledgeProduct) -> list[str]:
    payload = getattr(product, "selling_points_approved_json", None)
    if not isinstance(payload, dict) or payload.get("review_status") != "approved":
        return []
    bullets = payload.get("bullets")
    if not isinstance(bullets, list):
        return []
    texts: list[str] = []
    for bullet in bullets:
        if isinstance(bullet, dict):
            text = str(bullet.get("text") or "").strip()
            if text:
                texts.append(text)
    return texts


__all__ = ["GeoContentOrchestrator", "GeoContentError"]
