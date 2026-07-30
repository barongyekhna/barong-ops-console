"""把 AI 解读写回 GEO 的内容行——纯逻辑在 `content_core.analysis`。

这里只剩**持久化适配器**:它必须知道 GeoContentItem 这张表,所以按下沉判据
留在 GEO 侧;解读本身与内容种类无关,已经下沉。
"""

from __future__ import annotations

import logging
from typing import Any

from ...content_core.analysis import (  # noqa: F401 - 保持既有导入点可用
    analysis_instruction,
    analyze_content,
    analyze_item,
    coerce_json_result,
)
from ...content_core.analysis import _item_payload  # noqa: F401

logger = logging.getLogger(__name__)


def attach_analysis_safely(
    db: Any, items: list[Any], *, topic: str, user: Any | None = None
) -> int:
    """Analyse each piece and persist it, one short transaction at a time.

    死规矩(本仓库踩过两次): never hold a DB transaction across an outbound call.
    Snapshot every payload first, COMMIT to release the read transaction, then do
    the (~30s each) DeepSeek round trips with no transaction open, writing each
    result in its own short-lived session. Holding the session across five calls
    got the connection killed by the idle-in-transaction timeout.
    """
    from ....db.session import SessionLocal
    from sqlalchemy import update

    from .models import GeoContentItem

    snapshots = [(item.id, _item_payload(item)) for item in items]
    if not snapshots:
        return 0
    # Release the transaction BEFORE any network call.
    db.commit()

    done = 0
    for item_id, payload in snapshots:
        try:
            result = analyze_content(payload, topic=topic, user=user)
        except Exception:  # noqa: BLE001 - belt and braces
            logger.exception("GEO analysis crashed for item %s", item_id)
            result = None
        if not result:
            continue
        try:
            with SessionLocal() as writer:
                writer.execute(
                    update(GeoContentItem)
                    .where(GeoContentItem.id == item_id)
                    .values(analysis_json=result)
                )
                writer.commit()
            done += 1
        except Exception:  # noqa: BLE001 - persistence of a reading aid is optional
            logger.exception("GEO analysis persist failed for item %s", item_id)
    return done


__all__ = [
    # 前四个由 content_core.analysis 提供,这里转出以保持既有导入点可用
    "analysis_instruction",
    "coerce_json_result",
    "analyze_content",
    "analyze_item",
    "attach_analysis_safely",
]
