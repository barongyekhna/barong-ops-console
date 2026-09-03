"""Async, parallel copy / image-brief generation for K product knowledge.

Endpoints enqueue rows into ``k_generation_jobs``; ``KGenerationJobWorker`` polls
the queue and runs the (~80-100s) orchestrator generate methods concurrently in a
thread pool -- so a batch of N products finishes in ~one generation instead of N
serial ones. The generated content lands on the product itself
(marketing_copy_json / image_instruction_json); this queue only tracks lifecycle
so the UI can poll and the operator can review when done.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ....models.user import User
from .scope_shim import KScopeContext, normalize_scope_context
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .selling_points_jobs import run_selling_points_job
from .workflow_engine import KWorkflowOrchestratorV2

_LOGGER = logging.getLogger("k-generation-jobs")

JOB_TYPES = ("marketing_copy", "image_brief", "brand_audit", "selling_points")
_TABLE = "k_generation_jobs"

# 未完成状态。入队去重与 partial unique index
# (uq_k_gen_jobs_active_product_type) 用的是同一套判据。
_ACTIVE_STATUSES = ("pending", "running")

# 一小时内允许的渲染批次数上限（首轮 + 最多两轮自动重渲 = 3；留 1 给人工重跑）。
# 这是不依赖 attempt 计数的硬保险，见 _run_brand_audit_job。
_MAX_RECENT_RENDER_BATCHES = 4


def _worker_concurrency(value: int | None = None) -> int:
    if value is None:
        value = int(os.getenv("K_GENERATION_CONCURRENCY", "5"))
    return max(1, min(value, 16))


def _poll_seconds() -> float:
    return max(1.0, float(os.getenv("K_GENERATION_POLL_SECONDS", "3")))


# --- enqueue + status (called from the request path) -----------------------

def enqueue_generation_jobs(
    db: Session,
    *,
    product_ids: Sequence[UUID],
    job_type: str,
    user: User | None,
    scope_context: KScopeContext,
    batch_id: UUID | None = None,
) -> tuple[UUID, list[dict[str, Any]]]:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown_job_type:{job_type}")
    batch_id = batch_id or uuid4()
    created: list[dict[str, Any]] = []
    for product_id in product_ids:
        job_id = uuid4()
        # 去重:同产品同类型只要还有未完成的任务就直接复用,不再插新行。
        # ON CONFLICT 挂在 partial unique index 上,所以并发双击也只会留一条
        # (此前完全没有去重,连点两次 = worker 并发跑两遍同一个产品、
        # 都写回同一行,后写的赢,AI 费用白烧一倍)。
        row = db.execute(
            text(
                f"""
                INSERT INTO {_TABLE}
                    (id, product_id, job_type, status, batch_id,
                     requested_by_username, workspace_key, business_context, scope_mode)
                VALUES
                    (:id, :product_id, :job_type, 'pending', :batch_id,
                     :username, :workspace_key, :business_context, :scope_mode)
                ON CONFLICT (product_id, job_type)
                    WHERE status IN ('pending', 'running')
                    DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": job_id,
                "product_id": product_id,
                "job_type": job_type,
                "batch_id": batch_id,
                "username": user.username if user is not None else None,
                "workspace_key": scope_context.workspace_key,
                "business_context": scope_context.business_context,
                "scope_mode": scope_context.scope_mode,
            },
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).first()
        if row is None:
            # 已有在途任务:回报那一条,让前端接着轮它而不是以为没反应。
            existing = db.execute(
                text(
                    f"""
                    SELECT id, status FROM {_TABLE}
                    WHERE product_id = :product_id AND job_type = :job_type
                      AND workspace_key = :workspace_key
                      AND status IN ('pending', 'running')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "product_id": product_id,
                    "job_type": job_type,
                    "workspace_key": scope_context.workspace_key,
                },
                execution_options=SKIP_ORG_DATA_ISOLATION,
            ).mappings().first()
            if existing is not None:
                created.append(
                    {
                        "job_id": str(existing["id"]),
                        "product_id": str(product_id),
                        "job_type": job_type,
                        "status": existing["status"],
                        "deduplicated": True,
                    }
                )
                continue
            # 竞态:刚刚那条在我们查之前就结束了。重试一次插入。
            row = db.execute(
                text(
                    f"""
                    INSERT INTO {_TABLE}
                        (id, product_id, job_type, status, batch_id,
                         requested_by_username, workspace_key, business_context, scope_mode)
                    VALUES
                        (:id, :product_id, :job_type, 'pending', :batch_id,
                         :username, :workspace_key, :business_context, :scope_mode)
                    ON CONFLICT (product_id, job_type)
                        WHERE status IN ('pending', 'running')
                        DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": job_id,
                    "product_id": product_id,
                    "job_type": job_type,
                    "batch_id": batch_id,
                    "username": user.username if user is not None else None,
                    "workspace_key": scope_context.workspace_key,
                    "business_context": scope_context.business_context,
                    "scope_mode": scope_context.scope_mode,
                },
                execution_options=SKIP_ORG_DATA_ISOLATION,
            ).first()
            if row is None:
                continue
        created.append({"job_id": str(job_id), "product_id": str(product_id), "job_type": job_type, "status": "pending"})
    return batch_id, created


def jobs_status(
    db: Session,
    *,
    batch_id: UUID | None = None,
    product_id: UUID | None = None,
    limit: int = 200,
    scope_context: KScopeContext | None = None,
) -> list[dict[str, Any]]:
    """任务面板。**走 API 请求线程,所以必须按 workspace 过滤。**

    ``k_generation_jobs`` 用 workspace_key 分区(不是 org_id):裸 SQL 既要显式
    带 workspace 过滤(跨组织隔离),又要用单语句逃生口让 C18G 放行这一条。
    基线条件写死在 clauses 初值里,可选条件只能往后追加 —— 否则一旦两个
    可选条件都不传,过滤就整条消失了(GEO 样板同款写法)。
    """
    scope = normalize_scope_context(scope_context)
    clauses = ["workspace_key = :workspace_key"]
    params: dict[str, Any] = {
        "limit": max(1, min(limit, 500)),
        "workspace_key": scope.workspace_key,
    }
    if batch_id is not None:
        clauses.append("batch_id = :batch_id")
        params["batch_id"] = batch_id
    if product_id is not None:
        clauses.append("product_id = :product_id")
        params["product_id"] = product_id
    where = f"WHERE {' AND '.join(clauses)}"
    rows = db.execute(
        text(
            f"""
            SELECT id, product_id, job_type, status, error, skill_version,
                   stage, stage_errors, started_at, finished_at, created_at
            FROM {_TABLE}
            {where}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    return [
        {
            "job_id": str(r["id"]),
            "product_id": str(r["product_id"]),
            "job_type": r["job_type"],
            "status": r["status"],
            "error": r["error"],
            "skill_version": r["skill_version"],
            # 多阶段任务(卖点)靠这两个字段驱动前端的分步显示与真实进度条;
            # 单阶段任务永远是 None。
            "stage": r["stage"],
            "stage_errors": r["stage_errors"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        }
        for r in rows
    ]




# --- worker side -----------------------------------------------------------

def _claim_pending_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT id, product_id, job_type, requested_by_username,
                   workspace_key, business_context, scope_mode
            FROM {_TABLE}
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings().all()
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'running', started_at = now(), attempts = attempts + 1,
                updated_at = now()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return [dict(r) for r in rows]


def _set_job_status(
    job_id: UUID,
    status: str,
    *,
    error: str | None = None,
    skill_version: str | None = None,
) -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                f"""
                UPDATE {_TABLE}
                SET status = :status, error = :error, skill_version = :skill_version,
                    finished_at = now(), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "error": error, "skill_version": skill_version},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        db.commit()


def _process_generation_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    try:
        with SessionLocal() as db:
            username = job.get("requested_by_username")
            user = (
                db.query(User).filter(User.username == username).first()
                if username
                else None
            )
            scope = KScopeContext(
                workspace_key=job["workspace_key"],
                business_context=job["business_context"],
                scope_mode=job["scope_mode"],
            )
            if job["job_type"] == "brand_audit":
                skill_version = _run_brand_audit_job(db, job=job, user=user, scope=scope)
                db.commit()
                _set_job_status(job_id, "completed", skill_version=skill_version)
                return
            if job["job_type"] == "selling_points":
                # 三阶段(bullets → zh → copy),每阶段自己写库 + commit,
                # 所以这里不再统一 commit。
                skill_version = run_selling_points_job(
                    db, job=job, user=user, scope=scope
                )
                _set_job_status(job_id, "completed", skill_version=skill_version)
                return
            orchestrator = KWorkflowOrchestratorV2(db)
            if job["job_type"] == "marketing_copy":
                product = orchestrator.generate_marketing_copy(
                    product_id=job["product_id"], scope_context=scope, request=None, user=user
                )
                skill_version = product.marketing_copy_skill_version
            elif job["job_type"] == "image_brief":
                product = orchestrator.generate_image_brief(
                    product_id=job["product_id"], scope_context=scope, request=None, user=user
                )
                skill_version = product.image_instruction_skill_version
            else:
                # 此前这里是 `else:` 兜底跑 image_brief —— 任何新加的 job_type
                # 只要忘了在上面加分支,就会静默跑成作图指令生成,不报错、
                # 状态还标 completed。宁可炸出来。
                raise RuntimeError(f"unhandled job_type: {job['job_type']}")
            db.commit()
        _set_job_status(job_id, "completed", skill_version=skill_version)
    except Exception as exc:  # noqa: BLE001 - isolate one job's failure
        _set_job_status(job_id, "failed", error=str(exc)[:1000])


def _run_brand_audit_job(
    db: Session,
    *,
    job: dict[str, Any],
    user: User | None,
    scope: KScopeContext,
) -> str:
    """品牌审查 + 自动闭环：检出图像违规（且无文本违规、轮数未耗尽）时自动
    重渲染违规图（带检出位置强化提示），渲染批次收尾会再次入队审查。"""
    from ....modules.notifications.service import create_notification
    from .brand_guard import run_brand_audit
    from .image_render_jobs import EXTERNAL_SUBMISSION_TAG, enqueue_image_render_jobs
    from .models import KProductKnowledgeProduct

    from .models import KProductKnowledgeMediaAsset

    product = db.get(KProductKnowledgeProduct, job["product_id"])
    if product is None:
        raise RuntimeError("product not found for brand audit")
    prev = product.brand_audit_json if isinstance(product.brand_audit_json, dict) else {}
    attempt = int(prev.get("attempt") or 0)
    audit = run_brand_audit(db, product=product, user=user, attempt=attempt)

    image_violations = audit.get("image_violations") or []
    text_violations = audit.get("text_violations") or []
    # 2026-08-03 熊猫花洒推翻了「几何变形重渲也修不好」这个旧结论:同一份 prompt、
    # 同一个批次里 4 张保真很好、4 张画崩了(电源键变成空椭圆/黑圆/脸被压宽),
    # 说明这是抽卡波动,不是生成式上限。所以几何/物理违规和品牌违规走同一条自动
    # 重渲路径,带上「上一版哪里画错了」的定向提示,沿用 attempt<2 上限;
    # 2 轮还不过才挡下来交人工。
    brand_image_violations = [
        v for v in image_violations if v.get("category") == "brand"
    ]
    geometry_violations = [
        v for v in image_violations if v.get("category") == "geometry"
    ]
    physics_violations = [
        v for v in image_violations if v.get("category") == "physics"
    ]
    # 可重渲修复的图像违规(全部三类)。文本违规仍然一票否决——文案得先改对。
    rerenderable_violations = [
        v
        for v in image_violations
        if v.get("category") in ("brand", "geometry", "physics")
    ]
    # 不依赖 attempt 的硬保险：直接数这个产品最近 1 小时真实发生过多少个渲染
    # 批次。attempt 计数曾经因为落库问题一直停在 0，靠它兜底 = 无限重渲无限
    # 烧额度。这条按数据库事实封顶，计数逻辑再坏也烧不穿。
    recent_batches = int(
        db.execute(
            text(
                """
                SELECT count(DISTINCT batch_id) FROM k_image_render_jobs
                WHERE product_id = :pid
                  AND created_at > now() - interval '1 hour'
                """
            ),
            {"pid": product.id},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        ).scalar()
        or 0
    )
    rerender_started = False
    if (
        not audit["clean"]
        and rerenderable_violations
        and not text_violations
        and not audit.get("errors")
        and attempt < 2
        and recent_batches <= _MAX_RECENT_RENDER_BATCHES
    ):
        # 违规图分两类：position 还在当前作图指令里的 → 重渲染；
        # 不在的（指令改小后残留的孤儿旧图）→ 直接归档，渲染不了它。
        instruction = product.image_instruction_json
        images = (
            instruction.get("images")
            if isinstance(instruction, dict)
            else None
        ) or []
        brief_positions = set()
        for index, spec in enumerate(images, start=1):
            if isinstance(spec, dict):
                try:
                    brief_positions.add(int(spec.get("position") or index))
                except (TypeError, ValueError):
                    brief_positions.add(index)
        hints: dict[int, str] = {}
        orphans_archived = 0
        for violation in rerenderable_violations:
            if violation.get("position") is None:
                continue
            position = int(violation["position"])
            flagged = db.get(KProductKnowledgeMediaAsset, violation.get("asset_id"))
            if (
                flagged is not None
                and (flagged.metadata_json or {}).get("submitted_via")
                == EXTERNAL_SUBMISSION_TAG
            ):
                # 外部精修通道(MCP)交的稿:审查结果照写,但绝不让 worker 自动
                # 重渲盖掉它——外面的画师自己看报告改。
                continue
            if position in brief_positions:
                # 同一位号可能同时中品牌+几何+物理,提示合并后一起喂回渲染。
                finding = str(violation.get("finding") or "")
                existing = hints.get(position)
                hints[position] = f"{existing} | {finding}" if existing else finding
                continue
            asset = db.get(KProductKnowledgeMediaAsset, violation.get("asset_id"))
            if asset is not None:
                asset.status = "removed"
                db.add(asset)
                orphans_archived += 1
        try:
            if hints:
                enqueue_image_render_jobs(
                    db,
                    product=product,
                    user=user,
                    scope_context=scope,
                    positions=sorted(hints.keys()),
                    brand_removal_hints=hints,
                )
                rerender_started = True
            elif orphans_archived:
                # 只清了孤儿没有可渲染的 → 直接补一轮审查（内容已变）
                enqueue_generation_jobs(
                    db,
                    product_ids=[product.id],
                    job_type="brand_audit",
                    user=user,
                    scope_context=scope,
                )
                rerender_started = True
            if rerender_started:
                # 轮数必须**确实**落库：run_brand_audit 内部已经 flush 过一版
                # attempt(旧值)，这里要显式 flag_modified + flush 覆盖它，否则
                # 计数永远停在 0 = 上限形同虚设(2026-08-03 实测就是 0)。
                from sqlalchemy.orm.attributes import flag_modified

                audit["attempt"] = attempt + 1
                fresh = db.get(KProductKnowledgeProduct, product.id)
                if fresh is not None:
                    fresh.brand_audit_json = dict(audit)
                    flag_modified(fresh, "brand_audit_json")
                    db.add(fresh)
                    db.flush()
        except Exception:  # noqa: BLE001 - 渲染在跑等场景；审查结果照常落库
            rerender_started = False

    # 审查要跑十几次 vision 调用、耗时几分钟。期间运营者完全可能保存图片、
    # 重做某张——内容一变，刚存下的指纹就过期了，上架门禁会以「内容在品牌
    # 审查后有改动」把人挡在外面，而他明明刚刚才忽略放行过。
    # 2026-08-11 实测：06:50 开审 → 06:52 保存图 → 06:54 落库，指纹当场作废。
    # 这里自愈：审完发现内容又变了就再排一轮。内容不再变时第二轮指纹自然对上，
    # 循环终止；已忽略的发现会结转，所以重审不会把人工放行冲掉。
    if not rerender_started:
        try:
            from .brand_guard import brand_fingerprint

            fresh = db.get(KProductKnowledgeProduct, product.id)
            if fresh is not None and audit.get("fingerprint") != brand_fingerprint(
                db, fresh
            ):
                enqueue_generation_jobs(
                    db,
                    product_ids=[product.id],
                    job_type="brand_audit",
                    user=user,
                    scope_context=scope,
                )
        except Exception:  # noqa: BLE001 - 自愈失败不该淹掉本轮审查结果
            _LOGGER.warning("stale-fingerprint re-audit enqueue failed", exc_info=True)

    if audit["clean"]:
        # 品牌审查通过是常态：不再往铃铛塞「通过」通知——一个多图产品会渲染出
        # 二十多张图、每次收尾都审查一遍，条条「通过」会把铃铛刷到 99+。
        # 通过状态在产品页 brand_audit_json 里可见；只有抓到冒牌品牌 / 审查失败
        # 才通知。上架门禁读的是 brand_audit_json，不依赖此通知。
        return "brand-guard-v1"
    reason_labels = []
    if brand_image_violations:
        reason_labels.append(f"品牌标识 {len(brand_image_violations)} 张")
    if geometry_violations:
        reason_labels.append(f"产品画变形 {len(geometry_violations)} 张")
    if physics_violations:
        reason_labels.append(f"画面违反工作原理 {len(physics_violations)} 张")
    if rerender_started:
        title = (
            f"图像审查检出{('、'.join(reason_labels)) or '问题'}，已自动重渲染"
            f"（第 {int(attempt) + 1}/2 轮）"
        )
        level = "warning"
        body = "; ".join(
            f"第{violation.get('position')}张: {str(violation.get('finding'))[:80]}"
            for violation in rerenderable_violations[:8]
        )
    elif (
        (geometry_violations or physics_violations)
        and not text_violations
        and not audit.get("errors")
    ):
        # 重渲轮数已用尽(或没有可重渲的位号)：挡发布，交人工。
        title = (
            f"审查检出{'、'.join(reason_labels)}，自动重渲已用尽："
            f"{product.sku or product.product_key}"
        )
        level = "error"
        body = (
            "已挡下发布（自动重渲 2 轮仍未通过）。请把这些位号改用真实产品照、"
            "人工换图，或先修正产品的「工作原理」再重渲："
            + "; ".join(
                f"第{violation.get('position')}张: {str(violation.get('finding'))[:80]}"
                for violation in (geometry_violations + physics_violations)[:6]
            )
        )
    else:
        title = f"品牌审查未通过：{product.sku or product.product_key}"
        level = "error"
        body = "; ".join(
            [
                f"{violation.get('term')}({violation.get('surface')})"
                for violation in text_violations[:6]
            ]
            + [
                f"第{violation.get('position')}张图有品牌标识"
                for violation in brand_image_violations[:6]
            ]
            + [
                f"第{violation.get('position')}张图产品变形"
                for violation in geometry_violations[:6]
            ]
            + [
                f"第{violation.get('position')}张图违反工作原理"
                for violation in physics_violations[:6]
            ]
            + ([f"{len(audit['errors'])} 步审查失败(fail-closed)"] if audit.get("errors") else [])
        )
    try:
        create_notification(
            db,
            event_type="k.brand_audit.finished",
            title=title,
            body=body,
            level=level,
            source="k.brand_guard",
            product_id=product.id,
            payload={
                "clean": audit["clean"],
                "text_violations": len(text_violations),
                "image_violations": len(image_violations),
                "brand_image_violations": len(brand_image_violations),
                "geometry_violations": len(geometry_violations),
                "physics_violations": len(physics_violations),
                "attempt": audit.get("attempt"),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return "brand-guard-v1"


class KGenerationJobWorker:
    """Polls k_generation_jobs and runs claimed jobs in a thread pool."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        concurrency: int | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.concurrency = _worker_concurrency(concurrency)
        self.poll_seconds = poll_seconds if poll_seconds is not None else _poll_seconds()

    def run_once(self, *, log: Callable[[str], None] | None = None) -> bool:
        with self.session_factory() as db:
            jobs = _claim_pending_jobs(db, self.concurrency)
        if not jobs:
            return False
        if log:
            log(f"K generation: claimed {len(jobs)} job(s), concurrency={self.concurrency}")
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(_process_generation_job, job) for job in jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    if log:
                        log(f"K generation job crashed: {exc}")
        return True

    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None] | None = None,
    ) -> None:
        if log:
            log(f"K generation worker started concurrency={self.concurrency} poll={self.poll_seconds:g}s")
        while not should_stop():
            try:
                did_work = self.run_once(log=log)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log(f"K generation worker loop error: {exc}")
                did_work = False
            if not did_work:
                time.sleep(self.poll_seconds)


def requeue_stale_running(db: Session, *, older_than_seconds: int = 900) -> int:
    """Reset jobs stuck in 'running' (e.g. after a worker restart) back to pending."""
    result = db.execute(
        text(
            f"""
            UPDATE {_TABLE}
            SET status = 'pending', updated_at = now()
            WHERE status = 'running'
              AND started_at < now() - (:secs || ' seconds')::interval
            """
        ),
        {"secs": str(older_than_seconds)},
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return result.rowcount or 0
