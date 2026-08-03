"""第①②步:挑选题、挑买家问句、派生成。

原本这两步只能去 GEO/SEO 两个老页面做,内容台只显示一个数字「11 个高分选题
还没挑」然后让人自己走开 —— 那等于把「你不知道下一步该干嘛」原样退还给用户。
用户 2026-08-03 原话:「这些都要在内容台操作啊,现在只能看到一个发布页面」。

两种要挑的东西,形状不一样,**不强行合并**:

- **SEO 选题** = 一个关键词。挑 = 把 status 从 candidate 改成 picked。
  分数已经把「有没有事实支撑」折进去了(0 分 = 零支撑),``geo_reachable``
  的题不进这个清单 —— 那是 GEO 的地盘,催 SEO 写就是两篇自家文章抢同一个查询。

- **GEO 簇** = 一整个类目。挑 = 从候选里勾买家问句。空问句**不阻塞**生成,
  只是退化成按产品规格写 —— 所以文案是「挑了才会回答真实买家问题」,
  不是「不挑不能生成」。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext

logger = logging.getLogger(__name__)

# 一次给人看多少条。挑选题是判断题,一屏放不下就没人挑了。
MAX_CANDIDATES = 12


def seo_candidates(db: Session, *, limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    """待挑的 SEO 选题,分高的在前。"""
    from ..seo_series.content.models import SeoTopic
    from .workflow import PICK_SCORE_FLOOR

    rows = db.execute(
        select(SeoTopic)
        .where(
            SeoTopic.status == "candidate",
            SeoTopic.score >= PICK_SCORE_FLOOR,
            SeoTopic.geo_reachable.is_(False),
        )
        .order_by(SeoTopic.score.desc(), SeoTopic.created_at)
        .limit(limit)
    ).scalars()
    out = []
    for topic in rows:
        support = topic.fact_support_json or {}
        out.append(
            {
                "id": str(topic.id),
                "keyword": topic.keyword,
                "audience": topic.audience,
                "destination": topic.destination,
                "score": topic.score,
                "searches": topic.avg_monthly_searches,
                "attackability": topic.attackability,
                "terrain": topic.terrain,
                "category_path": topic.category_path,
                # 能写什么、缺什么 —— 挑之前就该看见,不然挑完才发现没料。
                "supported": (support.get("supported") or [])[:3],
                "missing": (support.get("missing") or [])[:3],
            }
        )
    return out


def geo_clusters(db: Session) -> list[dict[str, Any]]:
    """**所有**话题簇 + 各自挑了几条 / 还有多少候选。

    2026-08-03 用户问:「那次选题出来 60 多个,内容台选题里怎么看不到?」
    两个真 bug 叠在一起:

    1. 原来只列 ``status == 'draft'`` 的簇。簇一旦生成过就变成 ``needs_review``,
       于是**再也不出现** —— 哪怕它一条问句都没挑。
    2. 原来只列「一条都没挑的」。挑了 2 条、库里还躺着 61 条候选的簇被当成
       「做完了」藏起来 —— 而那 61 条正是深耕的存货。

    **选题不是一次性的门槛,是一直在的货架。** 所以这里列全部,把「已挑 N /
    候选 M」摆出来,随时能进去再挑几条。
    """
    from sqlalchemy import func

    from ..geo_series.content.models import GeoContentCluster, GeoMinedQuestion

    mined = dict(
        db.execute(
            select(GeoMinedQuestion.cluster_id, func.count())
            .group_by(GeoMinedQuestion.cluster_id)
        ).all()
    )
    out = []
    for cluster in db.execute(select(GeoContentCluster)).scalars():
        if cluster.status == "archived":
            continue
        picked = len(cluster.picked_questions_json or [])
        out.append(
            {
                "id": str(cluster.id),
                "title": cluster.title,
                "topic": cluster.topic,
                "category_path": cluster.category_path,
                "product_count": len(cluster.product_ids_json or []),
                "picked_count": picked,
                # 已经挖出来、躺在库里的候选。**这就是深耕的存货**。
                "mined_count": int(mined.get(cluster.id, 0)),
            }
        )
    # 存货多、挑得少的排前面 —— 那是最值得再挑几条的。
    out.sort(key=lambda c: (c["picked_count"], -c["mined_count"]))
    return out


def set_seo_topic_status(
    db: Session, *, topic_id: UUID, status: str, user: Any
) -> dict[str, Any]:
    """挑中 / 不写。**不 commit**,handler 收尾。"""
    from ..seo_series.content import constants as C
    from ..seo_series.content.models import SeoTopic

    if status not in C.TOPIC_STATUSES:
        raise ValueError(f"未知状态 {status}。")
    topic = db.get(SeoTopic, topic_id)
    if topic is None:
        raise LookupError("这个选题不存在。")
    topic.status = status
    if status == "picked":
        topic.picked_by_user_id = getattr(user, "id", None)
    db.flush()
    return {"id": str(topic.id), "status": topic.status}


def cluster_questions(
    db: Session, *, cluster_id: UUID, scope: KScopeContext
) -> dict[str, Any]:
    """候选买家问句 + 已挑的。**不出新网** —— 复用 K 的 FAQ 研究、F 的关键词、
    以及 geo_mined_questions 这张已经挖好的表。"""
    from ..geo_series.content import service
    from ..geo_series.monitor.probe import normalize_question, terrain_by_question
    from ..geo_series.content.topic_sourcing import list_topic_candidates

    cluster = service.get_cluster(db, cluster_id=cluster_id, scope_context=scope)
    if cluster is None:
        raise LookupError("这个话题簇不存在。")
    candidates = list_topic_candidates(db, cluster=cluster, scope_context=scope)
    # 阵地数据挂到候选上:挑的时候就看得见「这条打不打得动」,
    # 而不是写完发布了才发现前排全是守门人榜单。
    try:
        terrain = terrain_by_question(db, cluster_id=cluster_id)
        for candidate in candidates:
            reading = terrain.get(
                normalize_question(str(candidate.get("question") or ""))
            )
            candidate["terrain"] = reading or None
    except Exception:  # noqa: BLE001 - 阵地是增益,取不到不该让人挑不了题
        logger.exception("terrain lookup failed for cluster %s", cluster_id)
    return {
        "cluster": {"id": str(cluster.id), "title": cluster.title},
        "candidates": candidates,
        "picked": cluster.picked_questions_json or [],
    }


def save_cluster_questions(
    db: Session,
    *,
    cluster_id: UUID,
    questions: list[dict[str, Any]],
    scope: KScopeContext,
    user: Any,
) -> None:
    from ..geo_series.content import service

    cluster = service.save_picked_questions(
        db, cluster_id=cluster_id, scope_context=scope, questions=questions, user=user
    )
    if cluster is None:
        raise LookupError("这个话题簇不存在。")


def generate_seo(
    db: Session, *, topic_ids: list[UUID], scope: KScopeContext, user: Any
) -> int:
    """派 SEO 生成。**排队**,真正的生成在 seo-worker 里跑(AI 一分钟起步)。"""
    from ..seo_series.content.generation_jobs import enqueue_seo_jobs

    created = enqueue_seo_jobs(
        db, topic_ids=topic_ids, user=user, scope_context=scope
    )
    return len(created)


def generate_geo(
    db: Session, *, cluster_id: UUID, scope: KScopeContext, user: Any
) -> int:
    """派 GEO 整簇生成。"""
    from ..geo_series.content.generation_jobs import enqueue_geo_jobs

    _batch, jobs = enqueue_geo_jobs(
        db, cluster_ids=[cluster_id], user=user, scope_context=scope
    )
    return len(jobs)


def picked_awaiting_generation(db: Session) -> list[dict[str, Any]]:
    """已挑中但还没有文章的 —— 第②步的待办。"""
    from ..seo_series.content.models import SeoContentItem, SeoTopic

    written = {
        row[0]
        for row in db.execute(select(SeoContentItem.topic_id)).all()
    }
    out = []
    for topic in db.execute(
        select(SeoTopic).where(SeoTopic.status == "picked")
    ).scalars():
        if topic.id in written:
            continue
        out.append(
            {"id": str(topic.id), "keyword": topic.keyword, "audience": topic.audience}
        )
    return out


__all__ = [
    "MAX_CANDIDATES",
    "cluster_questions",
    "generate_geo",
    "generate_seo",
    "geo_clusters",
    "picked_awaiting_generation",
    "save_cluster_questions",
    "seo_candidates",
    "set_seo_topic_status",
]
