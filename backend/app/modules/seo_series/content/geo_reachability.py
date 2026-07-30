"""GEO 可达性判定——**SEO 和 GEO 之间那道去重门**。

同一个话题两边都写就是自我竞争:两篇自家文章抢同一个查询,权重对半分,
AI 答案引擎还得在两个自家来源里挑一个。这是 GEO 一开始就定死的规矩
(一类目一簇、绝不建重复簇)的自然延伸,只是这次跨的是模块边界。

**判据不是人拍脑袋,是按 GEO 自己的规则反推**——三项全中才算 GEO 领地:

1. 这题能不能映射到已有簇的谷歌类目?(GEO 按类目组织内容,没类目它写不了)
2. 过不过 GEO 的买家问句门 ``topic_sourcing._accept``?(不是真问句它也不收)
3. 是不是已经被现有 GEO 内容覆盖了?(问句归一化比对)

任一不中 → 落 SEO,并**写明为什么**。理由不是记录癖:运营看到"无对应类目"
和看到"被 GEO 收了"要做的事完全不同。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip("?").strip()


def _cluster_category_terms(db: Session) -> set[str]:
    """已有 GEO 簇覆盖的类目词。类目路径拆成词,好做宽松包含判断。"""
    from ...geo_series.content.models import GeoContentCluster

    terms: set[str] = set()
    rows = db.execute(
        select(GeoContentCluster.category_path, GeoContentCluster.topic)
    ).all()
    for path, topic in rows:
        for chunk in re.split(r"[>/,]", str(path or "")):
            cleaned = normalize(chunk)
            if len(cleaned) >= 4:
                terms.add(cleaned)
        cleaned_topic = normalize(topic)
        if len(cleaned_topic) >= 4:
            terms.add(cleaned_topic)
    return terms


def _covered_questions(db: Session) -> set[str]:
    """GEO 已经写过的问句(含已选中待写的),归一化后比对。"""
    from ...geo_series.content.models import GeoContentCluster, GeoContentItem

    covered: set[str] = set()
    for (body,) in db.execute(select(GeoContentItem.body_json)).all():
        blocks = (body or {}).get("answer_blocks") if isinstance(body, dict) else None
        for block in blocks or []:
            if isinstance(block, dict):
                covered.add(normalize(block.get("question")))
    for (title,) in db.execute(select(GeoContentItem.title)).all():
        covered.add(normalize(title))
    for (picked,) in db.execute(select(GeoContentCluster.picked_questions_json)).all():
        for entry in picked if isinstance(picked, list) else []:
            if isinstance(entry, dict):
                covered.add(normalize(entry.get("question")))
            else:
                covered.add(normalize(entry))
    covered.discard("")
    return covered


class GeoReachability:
    """一次性把 GEO 侧的状态读进内存,之后每个候选词都是纯内存判断。

    为什么不每题查一次库:雷达一轮几百个候选,逐题查会把这件事变成 N+1;
    更要紧的是**出网调用前必须先放开事务**(idle-in-transaction 那条铁律),
    先一次性读完、再去打 Keyword Planner,才不会让读事务挂在出网调用上。
    """

    def __init__(self, db: Session) -> None:
        self.category_terms = _cluster_category_terms(db)
        self.covered = _covered_questions(db)

    def judge(self, keyword: str) -> tuple[bool, str]:
        """(GEO 够得到吗, 理由)。够得到 → SEO 不碰。"""
        norm = normalize(keyword)
        if not norm:
            return False, "空词"

        if norm in self.covered:
            return True, "GEO 已经写过这题了（重复内容=自我竞争）"

        in_category = any(term in norm or norm in term for term in self.category_terms)
        if not in_category:
            return False, "没有对应的 GEO 类目簇——跨类目上位话题，归 SEO"

        try:
            from ...geo_series.content.topic_sourcing import _accept
        except Exception:  # noqa: BLE001 - GEO 侧不可用时一律放给 SEO
            logger.exception("GEO accept gate unavailable; routing to SEO")
            return False, "GEO 选题门不可用，先归 SEO"

        if not _accept(keyword):
            return False, "不是干净的买家问句（GEO 的门收不了），归 SEO"

        return True, "属于 GEO 领地：有对应类目簇且过买家问句门"


__all__ = ["GeoReachability", "normalize"]
