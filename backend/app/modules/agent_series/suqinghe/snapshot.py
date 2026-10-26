"""每天早上的全局快照:她读这一份就知道店里什么情况。

每个数据源单独兜底:读不到的那一项标「读不到」,其余照常——不让一处故障拖垮整份快照
(反过来也不许把读不到当成 0,见家规「信息在链条中被压扁」)。

只读。唯一一次出网是查 Woo 上已上传产品的真实状态(草稿 / 已发布)。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION, without_org_data_isolation
from . import cards
from .constants import LA
from .models import SqhGoal, SqhSnapshot

logger = logging.getLogger(__name__)

_X = SKIP_ORG_DATA_ISOLATION
UNREADABLE = {"error": "读不到"}

STAGES = ("k_draft", "k_workflow", "blocked_gate", "ready_to_upload", "uploaded_draft", "published", "uploaded_unknown")
STAGE_LABELS = {
    "k_draft": "K 建档中",
    "k_workflow": "K 流水线进行中",
    "blocked_gate": "卡在 P 闸门",
    "ready_to_upload": "可以上架",
    "uploaded_draft": "已上传但还是草稿",
    "published": "已发布",
    "uploaded_unknown": "已上传(Woo 状态核不了)",
}


def la_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(LA).date()


# ---------------------------------------------------------------- 产品流水线


def _latest_upload_jobs(db: Session, product_ids: list[Any]) -> dict[str, Any]:
    from ...p_series.upload.models import PUploadJob

    if not product_ids:
        return {}
    rows = db.scalars(
        select(PUploadJob).where(PUploadJob.product_id.in_(product_ids)).order_by(PUploadJob.created_at),
        execution_options=_X,
    )
    latest: dict[str, Any] = {}
    for job in rows:
        latest[str(job.product_id)] = job
    return latest


def _latest_workflows(db: Session, product_ids: list[Any]) -> dict[str, Any]:
    from ...k_series.product_knowledge.models import KProductKnowledgeWorkflowExecution as W

    if not product_ids:
        return {}
    rows = db.scalars(select(W).where(W.product_id.in_(product_ids)).order_by(W.created_at), execution_options=_X)
    latest: dict[str, Any] = {}
    for row in rows:
        latest[str(row.product_id)] = row
    return latest


def _gate(db: Session, product: Any) -> list[str]:
    from ...p_series.upload.assemble import gate_blockers

    return list(gate_blockers(db, product))


def product_stage(*, product: Any, workflow: Any | None, gate: list[str] | None, job: Any | None, woo: dict[int, dict[str, Any]] | None) -> str:
    """一个产品在 R→K→I→P→Woo 链上走到哪了。纯函数,方便测试。"""
    if job is not None and getattr(job, "external_product_id", None):
        if woo is None:
            return "uploaded_unknown"
        try:
            state = woo.get(int(job.external_product_id))
        except (TypeError, ValueError):
            state = None
        if state is None:
            return "uploaded_unknown"
        return "published" if state.get("status") == "publish" else "uploaded_draft"
    if not getattr(product, "marketing_copy_json", None):
        if workflow is not None and getattr(workflow, "status", "") in {"created", "running", "blocked", "failed"}:
            return "k_workflow"
        return "k_draft"
    if gate:
        return "blocked_gate"
    return "ready_to_upload"


def products_section(db: Session) -> dict[str, Any]:
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    with without_org_data_isolation():
        products = list(
            db.scalars(
                select(P).where(P.parent_product_id.is_(None), P.review_status != "archived").order_by(P.created_at),
                execution_options=_X,
            )
        )
        ids = [p.id for p in products]
        workflows = _latest_workflows(db, ids)
        jobs = _latest_upload_jobs(db, ids)
        gates: dict[str, list[str] | None] = {}
        for product in products:
            if getattr(product, "marketing_copy_json", None):
                try:
                    gates[str(product.id)] = _gate(db, product)
                except Exception:  # noqa: BLE001 —— 单个产品闸门读不到,只标这个产品
                    logger.exception("gate_blockers failed product=%s", product.id)
                    db.rollback()
                    gates[str(product.id)] = None
        woo_ids: list[int] = []
        for job in jobs.values():
            try:
                if job.external_product_id:
                    woo_ids.append(int(job.external_product_id))
            except (TypeError, ValueError):
                continue
    # 出网前放掉读事务(8 秒 idle-in-transaction 铁律)。
    db.commit()
    woo: dict[int, dict[str, Any]] | None = None
    woo_checked = False
    if woo_ids:
        from ...content_core.wc_sync import fetch_product_states_safely

        woo = fetch_product_states_safely(db, woo_ids)
        woo_checked = woo is not None

    from .models import SqhDossier

    # 她自己建进 K、流水线在推的品(pipeline.py 管着,卡也由流水线自己发)
    mine = {
        str(pid)
        for pid in db.scalars(
            select(SqhDossier.k_product_id).where(SqhDossier.status == "created", SqhDossier.k_product_id.is_not(None)),
            execution_options=_X,
        )
    }
    rows: list[dict[str, Any]] = []
    for product in products:
        pid = str(product.id)
        gate = gates.get(pid)
        stage = product_stage(product=product, workflow=workflows.get(pid), gate=gate, job=jobs.get(pid), woo=woo)
        job = jobs.get(pid)
        workflow = workflows.get(pid)
        rows.append(
            {
                "product_id": pid,
                "sku": product.sku,
                "name": product.product_name_en or product.product_key,
                "stage": stage,
                "stage_label": STAGE_LABELS[stage],
                "workflow_status": getattr(workflow, "status", None),
                "workflow_step": getattr(workflow, "current_step", None),
                "gate_blockers": gate if gate is not None else ("读不到" if pid in gates else []),
                "upload_status": getattr(job, "status", None),
                "woo_id": getattr(job, "external_product_id", None),
                "mine": pid in mine,
            }
        )
    counts = Counter(row["stage"] for row in rows)
    return {
        "total": len(rows),
        "by_stage": {stage: counts.get(stage, 0) for stage in STAGES},
        "woo_checked": woo_checked if woo_ids else None,
        "items": rows,
    }


# ---------------------------------------------------------------- 其他数据源


def content_section(db: Session) -> dict[str, Any]:
    from ...content_desk.queries import step_counts

    with without_org_data_isolation():
        return dict(step_counts(db))


def workers_section(db: Session) -> dict[str, Any]:
    from ....services.worker_heartbeat import list_heartbeats

    beats = list_heartbeats(db)
    stale = [b["worker_name"] for b in beats if b.get("stale")]
    return {"total": len(beats), "stale": stale}


def keys_section(db: Session) -> dict[str, Any]:
    from ...key_health.service import key_health_summary

    with without_org_data_isolation():
        summary = key_health_summary(db)
    ok_statuses = {"healthy", "never_checked", "pending_review", "rate_limited"}
    failing: list[dict[str, Any]] = []
    retired = 0
    for item in summary.get("items", []):
        if item["status"] in ok_statuses:
            continue
        modules = sorted({b["module_id"] for b in item.get("bindings") or []})
        if not modules:
            # 没有任何在用绑定的坏钥匙(比如 10-21 换血时故意撤下的 4sapi 文字钥匙)不算故障——
            # 10-22 首跑时她把它们当成「K 卡住的主因」发了换钥匙卡,就是这里没分开。
            retired += 1
            continue
        failing.append(
            {"name": item["key_name"], "status": item["status"], "reason": item["reason_code"], "used_by": modules}
        )
    return {"counts": summary.get("counts", {}), "failing": failing, "failing_but_unused": retired}


def ai_section(db: Session) -> dict[str, Any]:
    del db
    from ....services.ai_usage_ledger import claude_daily_budget_usd, claude_spend_today_usd

    spent = claude_spend_today_usd()
    if spent is None:
        return dict(UNREADABLE)
    return {"claude_usd_today": round(spent, 4), "claude_daily_budget_usd": claude_daily_budget_usd()}


def approvals_section(db: Session) -> dict[str, Any]:
    from sqlalchemy import func

    from ....models.approval import ApprovalRequestRecord

    with without_org_data_isolation():
        pending = db.scalar(
            select(func.count()).select_from(ApprovalRequestRecord).where(ApprovalRequestRecord.status == "pending"),
            execution_options=_X,
        )
    return {"pending": int(pending or 0)}


def goals_section(db: Session, products: dict[str, Any] | None) -> list[dict[str, Any]]:
    goals = list(db.scalars(select(SqhGoal).where(SqhGoal.status == "active").order_by(SqhGoal.created_at), execution_options=_X))
    published = None
    if isinstance(products, dict) and "by_stage" in products:
        published = products["by_stage"].get("published", 0)
    out = []
    for goal in goals:
        metric = goal.metric if isinstance(goal.metric, dict) else {}
        current = published if metric.get("metric") == "published_products" else None
        out.append({"id": goal.id, "text": goal.text, "metric": metric, "current": current})
    return out


SOURCES = {
    "products": products_section,
    "content": content_section,
    "workers": workers_section,
    "keys": keys_section,
    "ai": ai_section,
    "approvals": approvals_section,
}


def _headline(snap: dict[str, Any]) -> str:
    products = snap.get("products")
    parts: list[str] = []
    if isinstance(products, dict) and "by_stage" in products:
        by = products["by_stage"]
        published = by.get("published", 0)
        target = None
        for goal in snap.get("goals") or []:
            metric = goal.get("metric") or {}
            if metric.get("metric") == "published_products":
                target = metric.get("target")
        if target:
            gap = max(0, int(float(target)) - published)
            parts.append(f"店里已发布 {published} 个品,离 {int(float(target))} 还差 {gap}")
        else:
            parts.append(f"店里已发布 {published} 个品")
        if by.get("uploaded_unknown"):
            parts.append(f"{by['uploaded_unknown']} 个已上传的品 Woo 状态核不了")
        if by.get("blocked_gate"):
            parts.append(f"{by['blocked_gate']} 个卡在 P 闸门")
        if by.get("ready_to_upload"):
            parts.append(f"{by['ready_to_upload']} 个可以上架")
    else:
        parts.append("产品流水线读不到")
    workers = snap.get("workers")
    if isinstance(workers, dict) and workers.get("stale"):
        parts.append(f"{len(workers['stale'])} 个后台进程掉线")
    keys = snap.get("keys")
    if isinstance(keys, dict) and keys.get("failing"):
        parts.append(f"{len(keys['failing'])} 把钥匙坏了")
    return ";".join(parts) + "。"


def _blockers(snap: dict[str, Any]) -> list[dict[str, Any]]:
    products = snap.get("products")
    if not isinstance(products, dict):
        return []
    out = []
    for item in products.get("items", []):
        if item["stage"] in {"blocked_gate", "uploaded_unknown", "k_workflow"} or (item["stage"] == "uploaded_draft"):
            reasons = item["gate_blockers"] if isinstance(item["gate_blockers"], list) else [str(item["gate_blockers"])]
            out.append({"product_id": item["product_id"], "product": item["name"], "sku": item["sku"], "stage": item["stage_label"], "reasons": reasons})
    return out


def build_snapshot(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    snap: dict[str, Any] = {"date": la_today(now).isoformat(), "generated_at": now.isoformat()}
    for key, fn in SOURCES.items():
        try:
            snap[key] = fn(db)
        except Exception:  # noqa: BLE001 —— 一个源读不到只标这一项
            logger.exception("snapshot source failed: %s", key)
            db.rollback()
            snap[key] = dict(UNREADABLE)
    try:
        snap["goals"] = goals_section(db, snap.get("products"))
    except Exception:  # noqa: BLE001
        logger.exception("snapshot source failed: goals")
        db.rollback()
        snap["goals"] = dict(UNREADABLE)
    snap["headline"] = _headline(snap)
    snap["blockers"] = _blockers(snap)
    return snap


def save_snapshot(db: Session, payload: dict[str, Any], *, now: datetime | None = None) -> SqhSnapshot:
    day = la_today(now)
    row = db.get(SqhSnapshot, day)
    if row is None:
        row = SqhSnapshot(snapshot_date=day, payload=payload)
    else:
        row.payload = payload
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------- 审批卡指纹


def _product_gate_fingerprint(db: Session, recheck: dict[str, Any]) -> str:
    """卡上提到的那个产品,现在的闸门理由 + 上传状态。和建卡时不一样就说明数据变了。"""
    from ...k_series.product_knowledge.models import KProductKnowledgeProduct as P

    product_id = str(recheck.get("product_id") or "")
    with without_org_data_isolation():
        product = None
        try:
            from uuid import UUID

            product = db.get(P, UUID(product_id), execution_options=_X)
        except (ValueError, TypeError):
            product = None
        if product is None:
            return cards.fingerprint({"product_id": product_id, "missing": True})
        gate = _gate(db, product) if getattr(product, "marketing_copy_json", None) else ["no_copy"]
        job = _latest_upload_jobs(db, [product.id]).get(str(product.id))
    return cards.fingerprint(
        {
            "product_id": product_id,
            "gate": sorted(gate),
            "upload": getattr(job, "status", None),
            "woo_id": getattr(job, "external_product_id", None),
        }
    )


cards.register_fingerprinter("product_gate", _product_gate_fingerprint)
