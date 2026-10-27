"""她在 K 里点的每一个按钮(第②步起,10-26)。

不另写一套 K 的逻辑:直接调 K 自己的接口函数(router 里的那个函数),和运营在 K 页面上点按钮走同一套校验、
同一套副作用(比如风险词审完要存关键词快照、卖点批准要逐条核证据)。

- 身份:批这件事的老板(家规:机器人永远零权限码,以说话人的身份过各模块的门)。进来先按 K 的判据核一遍
  这个人有没有 K 的修改权限(owner 直通),没有就不动手。
- 作用域:贸易公司(和建档 executor._scope 同一个),用一个只带 org_id 的替身请求传进去——
  K 的接口只从 request.state 里读组织;传 None 会落到默认工作区,找不到她建的产品。
- K 接口报错是 HTTPException / K 自己的异常,这里统一翻成 KOpError(code + 原话),由流水线决定重试还是报给老板。

K 的生成活(卖点、文案、作图指令、品牌审查)是排进 k_generation_jobs 让 k-worker 去跑的,这里只下单、查进度。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.requests import Request

from ....models.user import User
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION

logger = logging.getLogger(__name__)


class KOpError(RuntimeError):
    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail  # K 原样的报错内容(比如卖点逐条退回的 items),给调用方细看


def _detail_text(detail: Any) -> tuple[str, str]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or detail.get("reason") or "K_ERROR")
        message = str(detail.get("message") or detail.get("detail") or detail)
        items = detail.get("items") or detail.get("errors") or detail.get("missing_terms")
        if items:
            message += f" {items}"
        return code, message[:1500]
    return "K_ERROR", str(detail)[:1500]


def _call(fn: Any, **kwargs: Any) -> Any:
    """调 K 的接口函数,报错一律翻成 KOpError。"""
    from ...k_series.product_knowledge.errors import KProductKnowledgeError
    from ...k_series.product_knowledge.workflow_engine import KWorkflowExecutionError

    try:
        return fn(**kwargs)
    except HTTPException as exc:
        code, message = _detail_text(exc.detail)
        raise KOpError(code if code != "K_ERROR" else f"HTTP_{exc.status_code}", message, exc.detail) from exc
    except KWorkflowExecutionError as exc:
        raise KOpError(getattr(exc, "code", "K_WORKFLOW_ERROR"), str(exc)[:1500]) from exc
    except KProductKnowledgeError as exc:
        raise KOpError(exc.__class__.__name__, str(exc)[:1500]) from exc


def stand_in_request(org_id: str) -> Request:
    """替身请求:K 的接口只从 request.state 里读组织(api_support._scope_context、模块执行门)。"""
    return Request({"type": "http", "method": "POST", "path": "/suqinghe/k", "headers": [], "query_string": b"", "state": {"org_id": org_id}})


class KHands:
    """绑定了「替谁干、在哪个组织干」的 K 操作。一个实例只在一个数据库会话里用。"""

    def __init__(self, db: Session, *, actor: User, org_id: str) -> None:
        from ...k_series.product_knowledge.mcp_channel import KMcpChannelError, require_k_access

        try:
            require_k_access(db, actor, write=True)  # 和 K 页面同一判据(owner / super_admin 直通,否则看权限码)
        except KMcpChannelError as exc:
            raise KOpError("K_PERMISSION_DENIED", str(exc)) from exc
        self.db = db
        self.actor = actor
        self.org_id = org_id

    def _ctx(self) -> dict[str, Any]:
        return {"request": stand_in_request(self.org_id), "db": self.db, "user": self.actor}

    # ---- 关键词:K 工作流(富化 → SERP → 两道筛 → 停在风险词)----

    def start_keywords(self, product_id: UUID, *, main_keyword: str, seed_keywords: list[str]) -> Any:
        """同步跑完才返回(富化最慢能到十几分钟);失败不抛,执行记录里是 blocked + 错误码。"""
        from ...k_series.product_knowledge import router as k
        from ...k_series.product_knowledge.schemas import ProductKnowledgeWorkflowStartRequest

        payload = ProductKnowledgeWorkflowStartRequest(
            target_market="US", main_keyword=main_keyword, serp_query=main_keyword, seed_keywords=seed_keywords
        )
        return _call(k.product_knowledge_workflow_start, product_id=product_id, payload=payload, **self._ctx())

    def retry_keywords(self, product_id: UUID, *, step: str, main_keyword: str, seed_keywords: list[str]) -> Any:
        from ...k_series.product_knowledge import router as k
        from ...k_series.product_knowledge.schemas import ProductKnowledgeWorkflowControlRequest, ProductKnowledgeWorkflowStartRequest

        payload = ProductKnowledgeWorkflowControlRequest(
            step=step,
            workflow_payload=ProductKnowledgeWorkflowStartRequest(
                target_market="US", main_keyword=main_keyword, serp_query=main_keyword, seed_keywords=seed_keywords
            ),
        )
        return _call(k.product_knowledge_workflow_retry, product_id=product_id, payload=payload, **self._ctx())

    def review_risk(self, product_id: UUID, *, execution_id: UUID, decisions: list[dict[str, Any]]) -> Any:
        """每个风险词都要给 approve / reject;一个风险词都没有时要明说「确认没有」。审完 K 接着做关键词优化、单位换算。"""
        from ...k_series.product_knowledge import router as k
        from ...k_series.product_knowledge.schemas import ProductKnowledgeRiskReviewRequest

        payload = ProductKnowledgeRiskReviewRequest(execution_id=execution_id, decisions=decisions, confirm_no_risk_terms=not decisions)
        return _call(k.product_knowledge_workflow_risk_review, product_id=product_id, payload=payload, **self._ctx())

    # ---- 基础档案 ----

    def update_product(self, product_id: UUID, **fields: Any) -> Any:
        """K 页面「基础档案」的保存:改规格会作废已批的卖点和文案(K 自己的规矩)。"""
        from ...k_series.product_knowledge import router as k
        from ...k_series.product_knowledge.schemas import ProductKnowledgeUpdate

        return _call(k.product_knowledge_update, product_id=product_id, payload=ProductKnowledgeUpdate(**fields), **self._ctx())

    def sync_variants(self, product_id: UUID, *, product_type: str, variants: list[dict[str, Any]]) -> Any:
        """「基础档案」面板改类型和变体:多变体每个都要有价;payload 里没列的旧变体会被删(还挂着图的删不掉,409)。"""
        from ...k_series.product_knowledge import router as k
        from ...k_series.product_knowledge.schemas import ProductKnowledgeVariantsSync

        payload = ProductKnowledgeVariantsSync(product_type=product_type, variants=variants)
        return _call(k.product_knowledge_variants_sync, product_id=product_id, payload=payload, **self._ctx())

    def set_shipping(self, product: Any, *, shipping_class_slug: str, contains_battery: bool) -> None:
        """W-S 物流中枢的「手动指定运费模板」(和 W 页面同一个服务函数;W 的门槛是 w.site_ops.manage,owner 直通)。"""
        from ....core.roles import is_owner_role
        from ...w_series.shipping import service as shipping

        if not is_owner_role(getattr(self.actor, "role", "") or ""):
            raise KOpError("W_PERMISSION_DENIED", "指定运费模板要老板的身份。")
        try:
            shipping.manually_update_product(
                self.db,
                product,
                shipping_class_present=True,
                shipping_class_slug=shipping_class_slug,
                contains_battery_present=True,
                contains_battery=contains_battery,
                us_stock_present=False,
                us_stock=None,
                clear_review=True,
            )
        except ValueError as exc:
            raise KOpError("W_SHIPPING_INVALID", str(exc)) from exc
        self.db.commit()

    # ---- 文案、作图指令、出图(K 的任务队列 / 渲染队列,k-worker 去跑)----

    def generate_copy(self, product_id: UUID) -> Any:
        from ...k_series.product_knowledge import router as k

        return _call(k.product_knowledge_generate_copy, product_id=product_id, **self._ctx())

    def edit_copy(self, product_id: UUID, *, edits: dict[str, Any], reason: str, source: str = "suqinghe_review") -> Any:
        """K 的「按意见改文案」(10-27):逐字段改措辞,K 自己再过一遍证据校验;卖点原文和规格表不在这里改。

        改不了的字段 K 用 422 逐条退回(detail.items[].field / error),由流水线决定去掉那几项再交一次还是报给老板。
        """
        from ...k_series.product_knowledge import router as k

        payload = k.MarketingCopyEditRequest(edits=k.MarketingCopyEdits(**edits), reason=reason[:1000], source=source)
        return _call(k.product_knowledge_edit_marketing_copy, product_id=product_id, payload=payload, **self._ctx())

    def generate_image_brief(self, product_id: UUID) -> Any:
        from ...k_series.product_knowledge import router as k

        return _call(k.product_knowledge_generate_image_brief, product_id=product_id, **self._ctx())

    def render_images(self, product_id: UUID) -> Any:
        """按作图指令一次出全部位置;作图指令过期(卖点/规格变了)会 409 IMAGE_BRIEF_*_STALE。"""
        from ...k_series.product_knowledge import router as k

        return _call(k.product_knowledge_render_images, product_id=product_id, payload=k.RenderImagesRequest(positions=None), **self._ctx())

    def render_retry(self, product_id: UUID, *, batch_id: UUID) -> Any:
        from ...k_series.product_knowledge import router as k

        return _call(k.product_knowledge_render_images_retry, product_id=product_id, payload=k.RenderRetryRequest(batch_id=batch_id), **self._ctx())

    def render_rework(self, product_id: UUID, *, asset_id: UUID, extra_prompt: str) -> Any:
        """单张重做:原 prompt + 老板的修改意见。"""
        from ...k_series.product_knowledge import router as k

        payload = k.RenderReworkRequest(asset_id=asset_id, extra_prompt=extra_prompt[:2000])
        return _call(k.product_knowledge_render_rework, product_id=product_id, payload=payload, **self._ctx())

    def save_renders(self, product_id: UUID) -> Any:
        """K 页面的「保存」:暂存图转正、绑主图、再跑一遍品牌审查。只在老板批了审核卡之后调(机器人只能交稿)。"""
        from ...k_series.product_knowledge import router as k

        return _call(k.product_knowledge_render_assets_save, product_id=product_id, payload=None, **self._ctx())

    def dispatch(self, product_id: UUID) -> Any:
        """P 的「上架」:过门禁 → 排进上传队列 → n8n 推到 Woo(新品一律落草稿)。"""
        from ...p_series import router as p

        return _call(p.p_dispatch, product_id=product_id, channel="woocommerce", **self._ctx())

    # ---- 卖点 ----

    def generate_selling_points(self, product_id: UUID) -> Any:
        from ...k_series.product_knowledge import router as k

        return _call(k.generate_product_selling_points, product_id=product_id, **self._ctx())

    def approve_selling_points(self, product_id: UUID, *, bullets: list[dict[str, Any]], seo_keywords: list[str]) -> Any:
        from ...k_series.product_knowledge import router as k

        payload = k.ApproveSellingPointsRequest(bullets=bullets, seo_keywords=seo_keywords, source="suqinghe_review")
        return _call(k.approve_product_selling_points, product_id=product_id, payload=payload, **self._ctx())


# ---------------------------------------------------------------- 只读:查 K 的进度


def latest_execution(db: Session, product_id: Any) -> Any | None:
    from sqlalchemy import select

    from ...k_series.product_knowledge.models import KProductKnowledgeWorkflowExecution as W

    return db.scalar(
        select(W).where(W.product_id == product_id).order_by(W.created_at.desc()).limit(1),
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )


def latest_jobs(db: Session, product_id: Any) -> dict[str, dict[str, Any]]:
    """每种生成任务最近的一条(pending / running / completed / failed)。

    K 自己的 /generation-jobs 接口按默认工作区过滤,查不到贸易公司下的任务(10-26 查到的),这里直接查表。
    """
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (job_type) job_type, status, error, stage, created_at, finished_at, attempts "
            "FROM k_generation_jobs WHERE product_id = :p ORDER BY job_type, created_at DESC"
        ),
        {"p": str(product_id)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings()
    return {row["job_type"]: dict(row) for row in rows}


def failed_attempts(db: Session, product_id: Any, job_type: str, *, since: Any = None) -> int:
    """K 的生成任务失败了几次(``since`` 之后;老板批「再试」那一刻重新数)。"""
    sql = "SELECT count(*) FROM k_generation_jobs WHERE product_id = :p AND job_type = :t AND status = 'failed'"
    params: dict[str, Any] = {"p": str(product_id), "t": job_type}
    if since is not None:
        sql += " AND created_at > :since"
        params["since"] = since
    return int(db.execute(text(sql), params, execution_options=SKIP_ORG_DATA_ISOLATION).scalar() or 0)


def variant_rows(db: Session, product_id: Any) -> list[Any]:
    from sqlalchemy import select

    from ...k_series.product_knowledge.models import KProductKnowledgeVariant as V

    return list(db.scalars(select(V).where(V.product_id == product_id).order_by(V.created_at), execution_options=SKIP_ORG_DATA_ISOLATION))


__all__ = ["KHands", "KOpError", "failed_attempts", "latest_execution", "latest_jobs", "stand_in_request", "variant_rows"]
