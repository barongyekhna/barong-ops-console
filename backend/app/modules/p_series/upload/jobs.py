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

from ....services import n8n_dispatch

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


def _build_payload(job: PUploadJob, base: str) -> dict[str, object]:
    """这一单发给 n8n 的载荷。传输层在 `services/n8n_dispatch.py`。"""
    return {
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


_QUEUE = n8n_dispatch.QueueSpec(
    model=PUploadJob,
    webhook_env=N8N_WEBHOOK_ENV,
    build_payload=_build_payload,
    stale_error=(
        f"n8n 超过 {IN_FLIGHT_TIMEOUT_MINUTES} 分钟未回传，按失联处理"
        "（检查 n8n 执行记录后可重新上传）"
    ),
    in_flight_timeout_minutes=IN_FLIGHT_TIMEOUT_MINUTES,
)


def kick_queue(db: Session, *, public_base: str) -> PUploadJob | None:
    """队列引擎：先给失联的 in-flight 收尸，然后在「无 in-flight」时派下一单。

    实现在 `services/n8n_dispatch.py` —— 收口前这套逻辑在五个模块里各有一份，
    四条不变量（收僵尸 / 严格串行 / 先提交再发送 / 失败递归）由
    `tests/backend/test_n8n_queue_contract.py` 行为验证。
    """
    return n8n_dispatch.kick_queue(db, _QUEUE, public_base=public_base)

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
    # 幂等：已落定的重复回报不重复处理。
    #
    # 唯一例外——**迟到的成功回报可以翻案**。failed 有两种来源：n8n 明确报错
    # (事实)，和看门狗「超时未回传」(推测)。2026-08-11 实测过一次推测错杀：
    # 产品其实已经建进 Woo(草稿 4394)，只是 n8n 的回报节点被跳过，15 分钟后
    # 被判失联；此时人工补回报却被这条幂等挡在门外，账面永远是「失败」，
    # 而站上明明有货。事实必须能覆盖推测，否则对不上账。
    if job.status == "success":
        return job
    if job.status == "failed":
        timed_out = "未回传" in (job.error or "")
        if not (timed_out and status == "success"):
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

        # 新产品上架 → 该类目所有文章的产品卡片里立刻多一张。
        # **一篇文章都不用碰**:控制台只重推一个 option,插件渲染时查表。
        # 同样包在 safely 里——内链是增益,上架回报是本职。
        from ...content_links.link_push import refresh_link_map_safely

        refresh_link_map_safely(db)
    # 队列核心：这单落地了，自动放行下一单
    if public_base:
        try:
            kick_queue(db, public_base=public_base)
        except Exception:  # noqa: BLE001 - 踢队失败不影响本单回报落账
            pass
    return job
