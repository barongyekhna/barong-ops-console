"""把 AI 解读写回内容行——**表名由调用方传进来**,所以 GEO/SEO 共用一份。

原本这段只服务 GEO,唯一和 GEO 绑死的是 ``GeoContentItem`` 这一个符号。把它变成
参数之后,整段就与"写哪种内容"无关了,符合下沉判据。

真正值钱的不是这几行 update,是它的**事务纪律**:
死规矩(本仓库踩过两次)——绝不让数据库事务跨越出网调用。先快照、再 commit 放掉
读事务、然后逐条做 30 秒级的 DeepSeek 往返,每条结果用自己的短事务写回。
一次把五个调用圈在同一个 session 里,连接会被 idle-in-transaction 掐死。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update

from .analysis import _item_payload, analyze_content

logger = logging.getLogger(__name__)


def attach_analysis_to(
    db: Any,
    items: list[Any],
    *,
    model: Any,
    topic: str,
    user: Any | None = None,
) -> int:
    from ...db.session import SessionLocal

    # 快照本身也要能失败——**内容已经生成好了,不能因为解读组装出错就整篇丢掉**
    # (2026-07-30 实跑:SEO 的列名叫 item_kind,快照抛异常 → 整个 generate 回滚,
    # 一次 AI 调用的产出凭空消失)。解读是阅读辅助,永远不该有这种破坏力。
    snapshots: list[tuple[Any, dict[str, Any]]] = []
    for item in items:
        try:
            snapshots.append((item.id, _item_payload(item)))
        except Exception:  # noqa: BLE001
            logger.exception("analysis payload build failed for item %s", item.id)
    if not snapshots:
        return 0
    db.commit()  # 出网前放掉事务

    done = 0
    for item_id, payload in snapshots:
        try:
            result = analyze_content(payload, topic=topic, user=user)
        except Exception:  # noqa: BLE001 - 解读是阅读辅助,炸了不该毁内容
            logger.exception("content analysis crashed for item %s", item_id)
            result = None
        if not result:
            continue
        try:
            with SessionLocal() as writer:
                writer.execute(
                    update(model).where(model.id == item_id).values(analysis_json=result)
                )
                writer.commit()
            done += 1
        except Exception:  # noqa: BLE001
            logger.exception("content analysis persist failed for item %s", item_id)
    return done


__all__ = ["attach_analysis_to"]
