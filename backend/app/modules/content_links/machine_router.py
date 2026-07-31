"""内链网的机器端点——n8n 每天来敲一次门。

## 为什么需要定时兜底，而不是只靠事件触发

三个事件触发点(产品上架、GEO 发布、SEO 发布)覆盖不了一件事:
**控制台不知道你什么时候在 WordPress 里点了发布**。n8n 首推刻意落草稿,
发布是人手动的。所以每天必须回去批量核一次真实状态,再重算链接图——
这个道理和 B2B 批发页每日重发那条一模一样。

鉴权照 H 系列哨兵与 b2b 重发的写法:env 共享密钥 + ``compare_digest``,
**密钥没配一律 403**(fail-closed,绝不因为忘配环境变量就变成裸端点)。
token 值必须与 ``B2B_REPUBLISH_TOKEN`` 不同——两条流打不同的门。
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ...db.session import get_db

router = APIRouter(prefix="/content", tags=["content-links-machine"])

TOKEN_ENV = "CONTENT_LINKS_TOKEN"


@router.post("/link-map/refresh")
def refresh_link_map(
    x_content_links_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """每日兜底:先核线上真实发布状态,再重算并推送链接图。

    先刷状态是硬要求——不刷就会把草稿指南挂进卡片,访客点进去 404。
    两份 live_state 各刷各的表(GEO 一份、SEO 一份)。
    """
    expected = os.getenv(TOKEN_ENV) or ""
    supplied = x_content_links_token or ""
    if (
        not expected
        or not supplied
        or not secrets.compare_digest(
            expected.encode("utf-8"), supplied.encode("utf-8")
        )
    ):
        raise HTTPException(status_code=403, detail="content links token 无效。")

    from ..geo_series.content.live_state import (
        refresh_item_live_state_safely as refresh_geo,
    )
    from ..seo_series.content.live_state import (
        refresh_item_live_state_safely as refresh_seo,
    )
    from .link_push import refresh_if_due

    refresh_geo(db)
    refresh_seo(db)
    # 定时这一路走护栏(手动按钮才绕过);连着被触发过就会被指纹短路挡下。
    return refresh_if_due(db)


__all__ = ["TOKEN_ENV", "router"]
