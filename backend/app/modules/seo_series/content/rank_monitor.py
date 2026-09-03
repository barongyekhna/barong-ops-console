"""排名监测——单位从"买家问句"换成"关键词",其余完全复用 GEO 阵地监测。

**不建第二套表。** GEO 的 ``geo_monitor_*`` 记的是「一个查询串 → 前十名是谁 →
可攻度」,这件事与查询串是问句还是关键词无关。给它加一列 ``kind`` 区分来源,
比再造一套表 + 一套 Serper 台账 + 一套守门人识别划算得多——后者迟早会漂。

SEO 侧的用法:把 ``picked`` 状态的选题灌进监测名单,之后跟着 GEO 的定期扫描
一起跑。可攻度反过来喂回选题排序(``topic_radar.score_topic``),形成闭环:
**打不动的题会自己沉下去**。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import (
    KScopeContext,
    apply_scope_filters,
)
from .models import SeoTopic

logger = logging.getLogger(__name__)

MONITOR_KIND = "seo_keyword"


def seed_from_picked_topics(db: Session, *, scope_context: Any) -> int:
    """把已选中的选题加进监测名单。返回新加了几条。"""
    from ...geo_series.monitor.models import GeoMonitorQuestion
    from ...geo_series.monitor.probe import normalize_question

    existing = {
        normalize_question(q)
        for (q,) in db.execute(select(GeoMonitorQuestion.question)).all()
    }
    added = 0
    for topic in db.execute(
        select(SeoTopic).where(SeoTopic.status.in_(("picked", "written")))
    ).scalars():
        if normalize_question(topic.keyword) in existing:
            continue
        db.add(
            GeoMonitorQuestion(
                cluster_id=None,
                question=topic.keyword,
                intent=None,
                kind=MONITOR_KIND,
                is_active=1,
                workspace_key=scope_context.workspace_key,
                business_context=scope_context.business_context,
                scope_mode=scope_context.scope_mode,
            )
        )
        existing.add(normalize_question(topic.keyword))
        added += 1
    db.commit()
    return added


def apply_terrain_to_topics(db: Session) -> int:
    """把最新一次监测读数写回选题,并按新的可攻度重排。"""
    from ...geo_series.monitor.probe import normalize_question, terrain_by_question

    from .topic_radar import score_topic

    readings = terrain_by_question(db)
    if not readings:
        return 0
    touched = 0
    for topic in db.execute(select(SeoTopic)).scalars():
        reading = readings.get(normalize_question(topic.keyword))
        if not reading:
            continue
        topic.attackability = reading.get("attackability")
        topic.terrain = reading.get("terrain")
        support = topic.fact_support_json or {}
        topic.score = score_topic(
            audience=topic.audience,
            searches=topic.avg_monthly_searches,
            attackability=topic.attackability,
            has_support=bool(support.get("has_support")),
            store_type_gap=False,
        )
        touched += 1
    db.commit()
    return touched


def monitor_state(
    db: Session, *, scope_context: KScopeContext | None = None
) -> dict[str, Any]:
    """SEO 视角的监测面板:只看 kind='seo_keyword' 的那部分。

    ``scope_context`` 把监测词限定在调用者自己的 workspace——被监测的关键词与
    竞品阵地就是业务情报,绝不能跨组织泄漏。
    """
    from ...geo_series.monitor.models import GeoMonitorQuestion, GeoMonitorResult

    questions = list(
        db.execute(
            apply_scope_filters(
                select(GeoMonitorQuestion), GeoMonitorQuestion, scope_context
            ).where(GeoMonitorQuestion.kind == MONITOR_KIND)
        ).scalars()
    )
    by_id = {q.id: q for q in questions}
    latest: dict[Any, Any] = {}
    if by_id:
        for row in db.execute(
            apply_scope_filters(
                select(GeoMonitorResult), GeoMonitorResult, scope_context
            )
            .where(GeoMonitorResult.question_id.in_(list(by_id)))
            .order_by(GeoMonitorResult.checked_at.desc())
        ).scalars():
            latest.setdefault(row.question_id, row)
    return {
        "watched": len(questions),
        "rows": [
            {
                "keyword": q.question,
                "attackability": getattr(latest.get(q.id), "attackability", None),
                "terrain": getattr(latest.get(q.id), "terrain", None),
                "our_position": getattr(latest.get(q.id), "our_position", None),
                "checked_at": (
                    latest[q.id].checked_at.isoformat()
                    if q.id in latest and latest[q.id].checked_at
                    else None
                ),
            }
            for q in questions
        ],
    }


__all__ = [
    "MONITOR_KIND",
    "apply_terrain_to_topics",
    "monitor_state",
    "seed_from_picked_topics",
]
