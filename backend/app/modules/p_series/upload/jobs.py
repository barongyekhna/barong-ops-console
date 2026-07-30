"""P 上架台账 + 串行派单队列（→n8n）+ 回报。

队列语义（防 Woo 429 / 防乱序）：任何时刻最多只有 **一个** job 在 n8n 手里
（status='dispatched'）。新任务一律先入队（status='queued'），由 ``kick_queue``
在「无 in-flight」时取最老的一个真正 POST 给 n8n；n8n 回传结果
（``record_result``）后自动踢下一个。in-flight 超过超时时间没回传的标 failed
并继续队列（惰性检查，kick 时执行）。

派单：建 job（一单一钥 token）→ 入队 → kick。没配 env N8N_P_UPLOAD_WEBHOOK
时 job 停在 queued，等 URL 一填即通。
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PUploadJob

N8N_WEBHOOK_ENV = "N8N_P_UPLOAD_WEBHOOK"
# n8n 一单的正常时长 ~1-2 分钟（10 图中转）；15 分钟没回传视为该单失联。
IN_FLIGHT_TIMEOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_dispatch_job(
    db: Session,
    *,
    product_id: UUID,
    channel: str,
) -> PUploadJob:
    """建一个排队中的上架任务（不直接发 n8n —— kick_queue 决定何时发）。"""
    job = PUploadJob(
        job_id=uuid4().hex,
        product_id=product_id,
        channel=channel,
        status="queued",
        token=secrets.token_urlsafe(32),
    )
    db.add(job)
    db.flush()
    return job


def _send_to_n8n(job: PUploadJob, *, public_base: str) -> None:
    """真正把一单 POST 给 n8n webhook（调用方负责状态流转）。"""
    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if not webhook:
        raise RuntimeError("N8N_P_UPLOAD_WEBHOOK 未配置")
    base = (os.getenv("P_CALLBACK_BASE") or public_base).rstrip("/")
    payload = {
        "job_id": job.job_id,
        "product_id": str(job.product_id),
        "channel": job.channel,
        "package_url": (
            f"{base}/p/products/{job.product_id}/upload-package"
            f"?channel={job.channel}&token={job.token}"
        ),
        "callback_url": f"{base}/p/uploads/{job.job_id}/result",
        "token": job.token,
    }
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        response.read()


def kick_queue(db: Session, *, public_base: str) -> PUploadJob | None:
    """队列引擎：先给失联的 in-flight 收尸，然后在「无 in-flight」时派下一单。

    返回本次真正派出去的 job（没有则 None）。幂等，可被任何触发点安全调用
    （入队后 / n8n 回传后 / 台账页轮询时）。
    """
    # 1) 失联收尸：dispatched 超时的标 failed，腾出跑道
    deadline = _now() - timedelta(minutes=IN_FLIGHT_TIMEOUT_MINUTES)
    stale = db.scalars(
        select(PUploadJob)
        .where(PUploadJob.status == "dispatched")
        .where(PUploadJob.dispatched_at < deadline)
        .with_for_update(skip_locked=True)
    ).all()
    for job in stale:
        job.status = "failed"
        job.error = (
            f"n8n 超过 {IN_FLIGHT_TIMEOUT_MINUTES} 分钟未回传，按失联处理"
            "（检查 n8n 执行记录后可重新上传）"
        )
        job.finished_at = _now()
        db.add(job)
    if stale:
        db.flush()

    # 2) 跑道占用检查：还有 in-flight 就不派新单（严格串行）
    in_flight = db.scalar(
        select(PUploadJob.id).where(PUploadJob.status == "dispatched").limit(1)
    )
    if in_flight is not None:
        return None

    # 3) 取最老的 queued（行锁防并发触发点重复派单）
    job = db.scalars(
        select(PUploadJob)
        .where(PUploadJob.status == "queued")
        .order_by(PUploadJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None

    # 4) 先落库再发货(2026-07-23 竞态实锤):n8n 收到 webhook 后毫秒级回来
    #    取数,任务行若还没提交,取数按「token 无效」401 打回。所以必须先把
    #    dispatched 状态提交成既成事实,再发 webhook;发送失败由下面的
    #    except 收尸(兜底还有失联超时收尸)。
    job.status = "dispatched"
    job.dispatched_at = _now()
    db.add(job)
    db.commit()
    try:
        _send_to_n8n(job, public_base=public_base)
    except Exception as exc:  # noqa: BLE001 - 单发失败不阻塞队列
        job.status = "failed"
        job.error = f"dispatch failed: {exc}"[:500]
        job.finished_at = _now()
        db.add(job)
        db.commit()
        # 继续踢下一单（递归深度 = 连续失败单数，有限）
        return kick_queue(db, public_base=public_base)
    return job


def create_dispatch_job(
    db: Session,
    *,
    product_id: UUID,
    channel: str,
    public_base: str,
) -> PUploadJob:
    """单产品上架入口（K 名册按钮 / P 驾驶舱用）：入队 + 踢队列。"""
    job = enqueue_dispatch_job(db, product_id=product_id, channel=channel)
    kick_queue(db, public_base=public_base)
    db.refresh(job)
    return job


def record_result(
    db: Session,
    *,
    job_id: str,
    token: str | None,
    status: str,
    external_product_id: str | None,
    external_url: str | None,
    error: str | None,
    public_base: str = "",
) -> PUploadJob | None:
    job = db.scalar(select(PUploadJob).where(PUploadJob.job_id == job_id))
    if job is None:
        return None
    if not token or token != job.token:
        raise PermissionError("invalid job token")
    # 幂等：已完成的重复回报不重复处理
    if job.status in ("success", "failed"):
        return job
    job.status = "success" if status == "success" else "failed"
    job.external_product_id = external_product_id
    job.external_url = external_url
    job.error = error
    job.finished_at = _now()
    db.flush()
    # 上架成功即灌进 B2B 批发目录（只建待填记录，不碰人工填过的批发价）。
    # 包在 safely 里：批发侧出任何问题都不许把上架回报带崩。
    if job.status == "success":
        from ...b2b.wholesale.ingest_from_k import (
            ingest_uploaded_product_safely,
        )

        woo_id: int | None = None
        if external_product_id and external_product_id.isdigit():
            woo_id = int(external_product_id)
        ingest_uploaded_product_safely(
            db,
            k_product_id=job.product_id,
            woo_product_id=woo_id,
        )
        # 上架成功即挂进 GEO 话题簇（一类目一簇：同类目产品共享话题，绝不建重复簇）。
        # 只建/挂簇，不生成内容——选题与生成仍要人工。同样包在 safely 里。
        from ...geo_series.content.ingest_from_p import (
            ensure_geo_cluster_for_product_safely,
        )

        ensure_geo_cluster_for_product_safely(db, k_product_id=job.product_id)
    # 队列核心：这单落地了，自动放行下一单
    if public_base:
        try:
            kick_queue(db, public_base=public_base)
        except Exception:  # noqa: BLE001 - 踢队失败不影响本单回报落账
            pass
    return job
