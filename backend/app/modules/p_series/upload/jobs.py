"""P 上架台账 + 派单（→n8n）+ 回报。

派单：建 job（一单一钥 token）→ 若配了 n8n webhook（env N8N_P_UPLOAD_WEBHOOK）就
POST 过去，n8n 拿 token 回来取数 + 回报。没配 webhook 就留 pending，等 URL 一填即通。
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.request
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PUploadJob

N8N_WEBHOOK_ENV = "N8N_P_UPLOAD_WEBHOOK"


def create_dispatch_job(
    db: Session,
    *,
    product_id: UUID,
    channel: str,
    public_base: str,
) -> PUploadJob:
    job = PUploadJob(
        job_id=uuid4().hex,
        product_id=product_id,
        channel=channel,
        status="pending",
        token=secrets.token_urlsafe(32),
    )
    db.add(job)
    db.flush()

    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if webhook:
        # n8n 用的回调 base（可指向内网/公网；裸路径 /p 绕过 /api/app 会话中间件）
        base = (os.getenv("P_CALLBACK_BASE") or public_base).rstrip("/")
        payload = {
            "job_id": job.job_id,
            "product_id": str(product_id),
            "channel": channel,
            "package_url": (
                f"{base}/p/products/{product_id}/upload-package"
                f"?channel={channel}&token={job.token}"
            ),
            "callback_url": f"{base}/p/uploads/{job.job_id}/result",
            "token": job.token,
        }
        try:
            req = urllib.request.Request(
                webhook,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                resp.read()
            job.status = "dispatched"
            job.dispatched_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - 派单失败 job 留 pending 可重试
            job.error = f"dispatch failed: {exc}"[:500]
    db.flush()
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
    job.finished_at = datetime.now(UTC)
    db.flush()
    return job
