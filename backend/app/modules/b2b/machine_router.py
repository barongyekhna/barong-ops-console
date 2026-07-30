"""B2B 产品页小窗的机器端点——token 鉴权,无会话。

n8n 拿不了控制台会话,所以这两条路由用一单一钥的 job token 鉴权,和 P 上架、
GEO 发布那两对完全一样。它们在 main.py 里**挂两次**:带 app 前缀的那份被
会话中间件守着,裸挂载的那份才是 n8n 真正打的。

单独成模块是有意的——面向人的路由永远不会不小心混进一条免鉴权的路由。
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import get_db
from .contract.widget_package import WidgetPackage
from .website import publisher as website_publisher
from .widget.jobs import record_result
from .widget.models import B2BWidgetJob
from .widget.service import package_for

router = APIRouter(prefix="/b2b", tags=["b2b-widget-machine"])


def _callback_base() -> str:
    public = os.getenv("PUBLIC_BASE_URL", "https://ops.barongyekhna.com").rstrip("/")
    return (os.getenv("P_CALLBACK_BASE") or public).rstrip("/")


class UpdatedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str | None = None
    woo_product_id: int | None = None
    ok: bool = True


class WidgetResultPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "success"
    updated_items: list[UpdatedItem] = Field(default_factory=list)
    error: str | None = None


@router.get("/widget-jobs/{job_id}/package", response_model=WidgetPackage)
def widget_package(
    job_id: str,
    token: str = Query(default=""),
    db: Session = Depends(get_db),
) -> WidgetPackage:
    """n8n 拉包。鉴权 = (job_id, token) 必须配对。

    包内容直接从 job 行里冻好的 targets_json 还原——**绝不重新推导**,
    否则派单后数据一变,n8n 拿到的和台账记的就不是一回事。
    """
    job = db.scalar(
        select(B2BWidgetJob)
        .where(B2BWidgetJob.job_id == job_id)
        .where(B2BWidgetJob.token == token)
    )
    if job is None:
        raise HTTPException(status_code=401, detail="token 无效。")
    return package_for(job)


@router.post("/widget-jobs/{job_id}/result")
def widget_result(
    job_id: str,
    payload: WidgetResultPayload,
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """n8n 回报。终态幂等:重试不会把成功改成失败。"""
    try:
        job = record_result(
            db,
            job_id=job_id,
            token=x_job_token,
            status=payload.status,
            updated_items=[item.model_dump() for item in payload.updated_items],
            error=payload.error,
            public_base=_callback_base(),
        )
    except PermissionError as error:
        raise HTTPException(status_code=401, detail="token 无效。") from error
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return {"job_id": job.job_id, "status": job.status}


@router.post("/website/republish")
def website_republish(
    x_b2b_republish_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """n8n 每天打一次:重新生成批发页,把新发布的指南捞上来。

    鉴权照 H 系列哨兵的写法(`h_series/sitehealth/router.py:463`):env 里的
    共享密钥 + `compare_digest`。**密钥没配就一律 403**——fail-closed,绝不
    因为忘了配环境变量就变成裸端点。

    为什么要定时而不是事件触发:控制台**不知道**用户什么时候在 WP 里点了
    发布(n8n 只落草稿,发布是手动的),所以只能定期回去核。
    """
    expected = os.getenv("B2B_REPUBLISH_TOKEN") or ""
    supplied = x_b2b_republish_token or ""
    if not expected or not supplied or not secrets.compare_digest(
        expected.encode("utf-8"), supplied.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="republish token 无效。")
    return website_publisher.republish_if_due(db)
