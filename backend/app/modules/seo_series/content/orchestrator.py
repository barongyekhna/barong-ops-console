"""SEO 文章生成编排。

与 GEO 编排器同构,复用同一批 content_core 能力(事实门禁 → 生成 → 守卫 →
AI 解读 → 批评 → 按批评重写),差别只在**喂什么事实**和**写什么形状**:

- GEO 喂产品规格,写买家问句问答块;
- SEO 喂**工艺事实 + 产品事实**,写编辑体文章。

工艺事实在这里不是可选增益,而是主料——一篇工艺文章没有工艺事实就只剩形容词。
所以这里的事实门禁比 GEO 严:**该受众的主事实源为空,直接拒绝生成并说明去补
什么**,不浪费一次 AI 调用,也不让运营以为系统在挑刺。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...content_core.guards import audit_content_item, evidence_number_corpus
from ...k_series.product_knowledge.brand_guard import SITE_BRAND
from . import constants as C
from .models import SeoContentItem, SeoTopic
from .prompt_skills import (
    SEO_CONTENT_SKILL_VERSION,
    seo_content_instruction,
    seo_revise_instruction,
)

logger = logging.getLogger(__name__)

_PROVIDER = "chatgpt"


class SeoContentError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class SeoContentOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- 事实装配 ---------------------------------------------------------------
    def _craft_facts(self, topic: SeoTopic) -> tuple[list[Any], list[dict[str, Any]]]:
        from ...content_core.facts import service as craft

        topics = [topic.craft_topic] if topic.craft_topic else None
        rows = craft.approved_facts(self.db, topics=topics)
        if not rows and topics:
            # 指定话题没有事实,退回全部已批准的——总比没有强,而且门禁在后面。
            rows = craft.approved_facts(self.db)
        payload = [
            {
                "topic": f.topic,
                "claim": f.claim,
                "detail": f.detail,
                "value": f.value,
                "unit": f.unit,
                "basis": f.basis,
            }
            for f in rows
        ]
        return rows, payload

    def _product_facts(self, topic: SeoTopic) -> list[dict[str, Any]]:
        """同类目的产品事实。SEO 文章点名产品要有据,不能靠模型印象。"""
        from ...k_series.product_knowledge.brand_guard import (
            sanitize_snapshot_for_generation,
        )
        from ...k_series.product_knowledge.buyer_display import (
            buyer_display_structured_specs,
        )
        from ...k_series.product_knowledge.models import KProductKnowledgeProduct

        query = select(KProductKnowledgeProduct)
        if topic.google_category_id:
            query = query.where(
                KProductKnowledgeProduct.google_product_category
                == topic.google_category_id
            )
        out: list[dict[str, Any]] = []
        for product in self.db.execute(query.limit(8)).scalars():
            snapshot = {
                "product_key": getattr(product, "product_key", None),
                "sku": getattr(product, "sku", None),
                "product_name": getattr(product, "product_name_en", None),
                "specs": buyer_display_structured_specs(product.structured_specs_json),
            }
            out.append(sanitize_snapshot_for_generation(snapshot, product))
        return out

    def _policy_facts(self) -> list[dict[str, Any]]:
        """B 端的采购政策事实——**试点跑出来的缺口**。

        2026-07-30 首篇 B 端文章诚实但空洞:它自己列了 9 条缺失事实
        (起订量、交期、付款、验厂…),因为当时只喂了产品规格,而**产品规格答不了
        采购问题**。这些答案其实早就有,只是住在 B2B 模块的政策常量里
        (那是用户自己拍板定的口径,批发页和产品页小窗都在用它)。

        接过来的另一个好处:批发页、小窗、SEO 文章从此**同一个口径**——
        同一件事两处说法不一,正是 GMC 判虚假陈述的那个病。
        """
        try:
            from ...b2b import policies as P
        except Exception:  # noqa: BLE001 - B2B 未就绪时当没有
            logger.exception("b2b policies unavailable")
            return []
        return [
            {
                "topic": "minimum-order",
                "claim": (
                    f"Minimum opening order is {P.DEFAULT_CURRENCY} "
                    f"{P.DEFAULT_MIN_ORDER_VALUE}; most lines start at one case."
                ),
                "value": str(P.DEFAULT_MIN_ORDER_VALUE),
                "unit": P.DEFAULT_CURRENCY,
            },
            {
                "topic": "shipping",
                "claim": (
                    f"Sea freight is free over {P.DEFAULT_CURRENCY} "
                    f"{P.FREE_SHIPPING_THRESHOLD}; shipments are "
                    f"{P.DELIVERY_LINE}."
                ),
                "value": str(P.FREE_SHIPPING_THRESHOLD),
                "unit": P.DEFAULT_CURRENCY,
            },
            {
                "topic": "payment-terms",
                "claim": P.PAYMENT_TERMS,
                "value": str(P.DEPOSIT_PERCENT),
                "unit": "percent deposit",
            },
            {
                "topic": "volume-pricing",
                "claim": (
                    f"Tiered pricing is negotiable from "
                    f"{P.VOLUME_DISCOUNT_MULTIPLE}x the minimum order; quotes "
                    f"stay valid {P.QUOTE_VALID_DAYS} days."
                ),
                "value": str(P.VOLUME_DISCOUNT_MULTIPLE),
                "unit": "x minimum order",
            },
            {
                "topic": "defects",
                # 死规矩:只讲瑕疵,绝不写成"X 天内可退"的结构化退货窗口
                # (那正是 GMC 判 Misrepresentation 的写法)。
                "claim": P.DEFECT_POLICY,
            },
            {
                "topic": "manufacturing",
                "claim": (
                    "In-house: " + ", ".join(P.WHOLESALE_INHOUSE) + ". "
                    "Partnered: " + ", ".join(P.WHOLESALE_PARTNERED) + "."
                ),
            },
        ]

    def _fact_gate(
        self,
        topic: SeoTopic,
        craft_payload: list[dict[str, Any]],
        product_payload: list[dict[str, Any]],
    ) -> None:
        """宁可不写,也不写正确的废话。拒绝时必须说清楚**去补什么**。"""
        if topic.audience == C.AUDIENCE_BRAND and not craft_payload:
            raise SeoContentError(
                "SEO_NO_CRAFT_FACTS",
                "这是工艺/品牌类选题，但工艺事实库里一条已批准的事实都没有。\n"
                "写出来只能是形容词。去「工艺事实」页录几条（每条要填依据），"
                "批准之后再来生成。",
                status_code=409,
            )
        if topic.audience == C.AUDIENCE_WHOLESALE and not (
            craft_payload or product_payload
        ):
            raise SeoContentError(
                "SEO_NO_FACTS",
                "这是 B 端采购类选题，但既没有工艺事实也没有同类目产品。\n"
                "采购方要看的是「你们到底能不能做」，没有事实就没有可写的。",
                status_code=409,
            )
        if topic.audience == C.AUDIENCE_CONSUMER and not product_payload:
            raise SeoContentError(
                "SEO_NO_PRODUCT_FACTS",
                "这是 C 端选题，但这个类目下 K 里没有产品事实。\n"
                "去 K 补规格/卖点，或把这个选题改成工艺/品牌向。",
                status_code=409,
            )

    # -- 生成 -------------------------------------------------------------------
    def generate(
        self,
        *,
        topic_id: UUID,
        scope_context: Any,
        user: Any | None,
        item_kind: str | None = None,
    ) -> SeoContentItem:
        topic = self.db.get(SeoTopic, topic_id)
        if topic is None:
            raise SeoContentError("SEO_TOPIC_NOT_FOUND", "这个选题不存在。", status_code=404)

        kind = item_kind or C.kinds_for(topic.audience)[0]
        if kind not in C.ITEM_KINDS:
            raise SeoContentError("SEO_BAD_KIND", f"未知体裁 {kind}。")

        craft_rows, craft_payload = self._craft_facts(topic)
        product_payload = self._product_facts(topic)
        # 采购政策只喂 B 端:C 端买家不关心起订量,给了只会污染文案。
        policy_payload = (
            self._policy_facts() if topic.audience == C.AUDIENCE_WHOLESALE else []
        )
        self._fact_gate(topic, craft_payload, product_payload)

        evidence_numbers = evidence_number_corpus(
            craft_payload, product_payload, policy_payload
        )
        forbidden_terms = self._forbidden_terms()

        ai_input = {
            "task": "seo_content_generation",
            "instruction": seo_content_instruction(
                item_kind=kind, audience=topic.audience
            ),
            "topic": topic.keyword,
            "audience": topic.audience,
            "item_kind": kind,
            "category_path": topic.category_path,
            "store_type": topic.store_type_key,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": forbidden_terms,
            "craft_facts": craft_payload,
            "products": product_payload,
            "wholesale_policy_facts": policy_payload,
        }

        # 出网前放掉事务(idle-in-txn 铁律)。
        self.db.commit()
        result = self._call_ai(ai_input, user)

        raw = result.get("item") if isinstance(result, dict) else None
        if not isinstance(raw, dict) or not raw.get("sections"):
            raise SeoContentError(
                "SEO_CONTENT_SCHEMA_INVALID",
                "内容提供方没有返回可用的 item。",
                status_code=502,
            )

        audit = audit_content_item(
            raw,
            forbidden_terms=forbidden_terms,
            evidence_numbers=evidence_numbers,
            context_numbers=None,
        )

        topic = self.db.get(SeoTopic, topic_id)
        item = SeoContentItem(
            topic_id=topic.id,
            item_kind=kind,
            destination=topic.destination,
            title=str(raw.get("title") or topic.keyword)[:512],
            body_json={"sections": raw.get("sections") or []},
            seo_json=raw.get("seo") if isinstance(raw.get("seo"), dict) else None,
            links_json={
                "intents": raw.get("link_intents") or [],
                # 模型自己说缺什么——这条会回流到工艺库的待补清单。
                "missing_facts": result.get("missing_facts") or [],
            },
            brand_audit_json=audit,
            generation_status="generated",
            review_status="pending",
            skill_version=SEO_CONTENT_SKILL_VERSION,
            provider=_PROVIDER,
            workspace_key=scope_context.workspace_key,
            business_context=scope_context.business_context,
            scope_mode=scope_context.scope_mode,
        )
        self.db.add(item)
        topic.status = "written"
        self.db.flush()

        self._record_craft_usage(str(item.id), craft_rows)

        from ...content_core.analysis_persist import attach_analysis_to

        attach_analysis_to(
            self.db, [item], model=SeoContentItem, topic=topic.keyword, user=user
        )
        self.db.commit()
        return self.db.get(SeoContentItem, item.id)

    # -- 重写 -------------------------------------------------------------------
    def revise(
        self, *, item_id: UUID, scope_context: Any, user: Any | None
    ) -> SeoContentItem:
        item = self.db.get(SeoContentItem, item_id)
        if item is None:
            raise SeoContentError("SEO_ITEM_NOT_FOUND", "这篇不存在。", status_code=404)
        analysis = item.analysis_json if isinstance(item.analysis_json, dict) else {}
        risks = [str(r) for r in (analysis.get("risks") or []) if str(r).strip()]
        if not risks:
            raise SeoContentError(
                "SEO_NO_CRITIQUE",
                "这篇还没有可用的批评意见——先生成 AI 解读。",
                status_code=409,
            )

        topic = self.db.get(SeoTopic, item.topic_id)
        craft_rows, craft_payload = self._craft_facts(topic)
        product_payload = self._product_facts(topic)
        policy_payload = (
            self._policy_facts() if topic.audience == C.AUDIENCE_WHOLESALE else []
        )
        evidence_numbers = evidence_number_corpus(
            craft_payload, product_payload, policy_payload
        )
        forbidden_terms = self._forbidden_terms()
        body = item.body_json if isinstance(item.body_json, dict) else {}
        round_no = 1
        if isinstance(item.revision_json, dict):
            try:
                round_no = int(item.revision_json.get("round") or 0) + 1
            except (TypeError, ValueError):
                round_no = 1

        ai_input = {
            "task": "seo_content_revision",
            "instruction": seo_revise_instruction(),
            "topic": topic.keyword,
            "site_brand": SITE_BRAND,
            "forbidden_brand_terms": forbidden_terms,
            "current_content": {
                "title": item.title,
                "sections": body.get("sections") or [],
                "seo": item.seo_json or {},
            },
            "critiques": risks,
            "craft_facts": craft_payload,
            "products": product_payload,
            "wholesale_policy_facts": policy_payload,
        }
        self.db.commit()
        result = self._call_ai(ai_input, user)
        revised = result.get("item") if isinstance(result, dict) else None
        if not isinstance(revised, dict):
            raise SeoContentError(
                "SEO_CONTENT_SCHEMA_INVALID",
                "重写提供方没有返回可用的 item。",
                status_code=502,
            )

        audit = audit_content_item(
            revised,
            # 重写会从零重算 audit——人工放行清单必须结转。
            previous_audit=item.brand_audit_json,
            forbidden_terms=forbidden_terms,
            evidence_numbers=evidence_numbers,
            context_numbers=None,
        )
        item = self.db.get(SeoContentItem, item_id)
        item.title = str(revised.get("title") or item.title)[:512]
        item.body_json = {"sections": revised.get("sections") or []}
        if isinstance(revised.get("seo"), dict):
            new_seo = dict(revised["seo"])
            # 死规矩:发布过的文章 slug 锁死。改地址 = 把积累的权重丢掉。
            if item.wp_post_id and isinstance(item.seo_json, dict):
                old_slug = (item.seo_json or {}).get("url_slug")
                if old_slug:
                    new_seo["url_slug"] = old_slug
            item.seo_json = new_seo
        if isinstance(revised.get("link_intents"), list):
            item.links_json = {
                **(item.links_json or {}),
                "intents": revised["link_intents"],
            }
        item.brand_audit_json = audit
        item.review_status = "pending"  # 重写作废上一次批准
        item.revision_json = {
            "round": round_no,
            "addressed": [str(a).strip() for a in (result.get("addressed") or [])],
            "unaddressed": result.get("unaddressed") or [],
        }
        item.analysis_json = None
        self._record_craft_usage(str(item.id), craft_rows)
        self.db.flush()

        from ...content_core.analysis_persist import attach_analysis_to

        attach_analysis_to(
            self.db, [item], model=SeoContentItem, topic=topic.keyword, user=user
        )
        self.db.commit()
        return self.db.get(SeoContentItem, item_id)

    # -- 杂项 -------------------------------------------------------------------
    def _forbidden_terms(self) -> list[str]:
        """第三方品牌黑名单。SEO 没有"本产品"这个锚点,所以取全库产品的品牌词。"""
        try:
            from ...k_series.product_knowledge.brand_guard import normalized_brand_terms
            from ...k_series.product_knowledge.models import KProductKnowledgeProduct

            terms: set[str] = set()
            for product in self.db.execute(
                select(KProductKnowledgeProduct).limit(200)
            ).scalars():
                terms.update(normalized_brand_terms(product))
            return sorted(terms)
        except Exception:  # noqa: BLE001 - 品牌门有自己的兜底,取不到不该毁生成
            logger.exception("brand term collection failed")
            return []

    def _record_craft_usage(self, content_id: str, facts: list[Any]) -> None:
        if not facts:
            return
        try:
            from ...content_core.facts.service import record_usage

            record_usage(
                self.db, content_kind="seo_item", content_id=content_id, facts=facts
            )
        except Exception:  # noqa: BLE001 - 台账记不上不该毁掉已生成的内容
            logger.exception("craft-fact usage ledger write failed")

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


__all__ = ["SeoContentError", "SeoContentOrchestrator"]
