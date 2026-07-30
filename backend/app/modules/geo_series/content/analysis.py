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
    """GEO 侧薄封装:唯一 GEO 专属的东西就是这张表。"""
    from ...content_core.analysis_persist import attach_analysis_to

    from .models import GeoContentItem

    return attach_analysis_to(
        db, items, model=GeoContentItem, topic=topic, user=user
    )


__all__ = [
    # 前四个由 content_core.analysis 提供,这里转出以保持既有导入点可用
    "analysis_instruction",
    "coerce_json_result",
    "analyze_content",
    "analyze_item",
    "attach_analysis_safely",
]
