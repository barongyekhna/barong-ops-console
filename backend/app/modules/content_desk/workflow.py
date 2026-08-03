"""四步导轨 + 待办清单。

**「卡在哪一步」是算出来的,不是手画的** —— 从①往④走,第一个**挡路的**待办
所在的步骤亮。「挡路」这个限定很关键,见 ``build_overview`` 里的注释。

用户原话:「我经常不知道自己下一步该干嘛了」。所以这里的每条待办都得是
**一句人话 + 一个动作**,不是一个状态码。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext

logger = logging.getLogger(__name__)

STEP_PICK = "pick"
STEP_GENERATE = "generate"
STEP_REVIEW = "review"
STEP_PUBLISH = "publish"

# 关键词雷达的分数已经把「有没有事实支撑」折进去了(0 分 = 零支撑)。
# 300 是个量纲参考:C 端有支撑的题通常 200-400,B 端缺口题 900、已覆盖 300,
# 工艺题固定 700。低于这个数催人去写,只会催出空话。
PICK_SCORE_FLOOR = 300


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    who: str


STEPS: tuple[Step, ...] = (
    Step(STEP_PICK, "选题", "机器挑 · 你可插手"),
    Step(STEP_GENERATE, "生成", "机器写"),
    Step(STEP_REVIEW, "你审", "只有这步要你"),
    Step(STEP_PUBLISH, "发布", "你点一下"),
)


def _scalar(db: Session, sql: str) -> int:
    try:
        return int(db.execute(text(sql)).scalar() or 0)
    except Exception:  # noqa: BLE001 - 一条判据查不动不该让整页打不开
        logger.exception("workflow probe failed: %s", sql)
        return 0


def _pick_counts(db: Session) -> tuple[int, int]:
    """(高分未挑的选题, 还没挑问句的簇)。

    ``geo_reachable`` 的题**排除掉** —— 那是 GEO 的地盘,催 SEO 写它就是让
    两篇自家文章抢同一个查询。
    """
    unpicked = _scalar(
        db,
        "SELECT count(*) FROM seo_topics "
        f"WHERE status = 'candidate' AND score >= {PICK_SCORE_FLOOR} "
        "AND geo_reachable = false",
    )
    # **不限 status='draft'**:簇生成过之后变成 needs_review,原来那个条件会让它
    # 再也不出现——哪怕一条问句都没挑(2026-08-03 捏捏簇就是这么消失的)。
    no_questions = _scalar(
        db,
        "SELECT count(*) FROM geo_content_clusters "
        "WHERE status <> 'archived' AND (picked_questions_json IS NULL "
        "OR picked_questions_json::text IN ('[]', 'null'))",
    )
    return unpicked, no_questions


def failed_jobs(db: Session) -> list[dict[str, Any]]:
    """两边生成任务里**还没被后来的成功盖过**的失败。

    SEO 的 ``jobs_status`` 自带 ``superseded``,GEO 没有 —— 一个三天前修好的
    GEO 失败会一直红着。这里给 GEO 也算一遍(照 SEO 那 6 行)。
    「修好的东西一直红着,比不显示更糟:它会让人对真正的报错脱敏。」
    """
    out: list[dict[str, Any]] = []
    try:
        from ..seo_series.content.generation_jobs import jobs_status as seo_jobs

        out += [
            {"source": "seo", "error": job.get("error"), "at": job.get("finished_at")}
            for job in seo_jobs(db)
            if job.get("status") == "failed" and not job.get("superseded")
        ]
    except Exception:  # noqa: BLE001
        logger.exception("seo job probe failed")
    try:
        from ..geo_series.content.generation_jobs import jobs_status as geo_jobs

        rows = geo_jobs(db)
        # GEO 的成功词是 completed(SEO 是 success),排队词是 pending(SEO 是 queued)。
        last_success: dict[Any, Any] = {}
        for job in rows:
            if job.get("status") == "completed":
                key = job.get("cluster_id")
                stamp = job.get("finished_at") or ""
                if stamp > last_success.get(key, ""):
                    last_success[key] = stamp
        for job in rows:
            if job.get("status") != "failed":
                continue
            stamp = job.get("finished_at") or ""
            if stamp < last_success.get(job.get("cluster_id"), ""):
                continue  # 后来成功过了,这条是历史
            out.append(
                {"source": "geo", "error": job.get("error"), "at": stamp}
            )
    except Exception:  # noqa: BLE001
        logger.exception("geo job probe failed")
    return out


def build_overview(db: Session, *, scope: KScopeContext | None = None) -> dict[str, Any]:
    """整页的载荷:四步导轨 + 待办。不出网。"""
    from . import queries

    counts = queries.step_counts(db, scope=scope)
    unpicked, no_questions = _pick_counts(db)
    failures = failed_jobs(db)

    pending = counts["pending_review"]
    to_publish = counts["approved_unpublished"]

    todos: list[dict[str, Any]] = []
    if pending:
        todos.append(
            {
                "step": STEP_REVIEW,
                "count": pending,
                "lead": f"{pending} 篇文章等你审",
                "note": "审完才能发。浮窗里能一口气过完。",
                "action": "review",
                "blocking": True,
            }
        )
    if to_publish:
        todos.append(
            {
                "step": STEP_PUBLISH,
                "count": to_publish,
                "lead": f"{to_publish} 篇已批准，还没发出去",
                "note": "发布前会先列出这次到底会发哪几篇。",
                "action": "publish",
                "blocking": True,
            }
        )
    # n8n **刻意**把文章落成草稿等人工发布。派单成功 ≠ 读者能看到 ——
    # 2026-08-03 用户发了两篇,任务 success、地址也有,匿名访问却是 404。
    # 发布的战报只说到派单、不说到读者能不能看见,那就是报了个假成功。
    drafts = _scalar(
        db,
        "SELECT count(*) FROM geo_content_items WHERE wp_post_id IS NOT NULL "
        "AND coalesce(wp_status,'') <> 'publish'",
    ) + _scalar(
        db,
        "SELECT count(*) FROM seo_content_items WHERE wp_post_id IS NOT NULL "
        "AND coalesce(wp_status,'') <> 'publish'",
    )
    if drafts:
        todos.append(
            {
                "step": STEP_PUBLISH,
                "count": drafts,
                "lead": f"{drafts} 篇已经在 WordPress 里，还是草稿",
                "note": "最后一步是你在 WP 后台点发布——在那之前读者看到的是 404。",
                "action": "publish",
                "blocking": True,
            }
        )
    if failures:
        todos.append(
            {
                "step": STEP_GENERATE,
                "count": len(failures),
                "lead": f"{len(failures)} 个生成任务失败了",
                "note": (failures[0].get("error") or "")[:80],
                "action": "engines",
                "blocking": True,
            }
        )
    if unpicked:
        todos.append(
            {
                "step": STEP_PICK,
                "count": unpicked,
                "lead": f"{unpicked} 个高分选题还没挑",
                "note": "在下面的清单里挑。GEO 够得到的题已经排除了（那是 GEO 的地盘）。",
                "action": "engines",
                # **不算挡路**:选题有存货是常态。见下面 here 的注释。
                "blocking": False,
            }
        )
    if no_questions:
        todos.append(
            {
                "step": STEP_PICK,
                "count": no_questions,
                "lead": f"{no_questions} 个话题簇还没挑买家问句",
                # 空问句**不阻塞**生成,只是退化成按产品规格写。别写成「不能生成」。
                "note": "挑了才会回答真实买家问题；不挑也能写，但只能按规格写。候选早就挖好了。",
                "action": "engines",
                "blocking": False,
            }
        )

    # 卡在哪一步 = 从①往④第一个**挡路的**待办。
    #
    # 关键是「挡路」这个限定。选题有存货是**常态**——雷达天天在跑,候选池永远
    # 不空。按「第一个有待办的」算,导轨会永远指着①,「现在卡在哪」这个信号当场
    # 作废。而这一页存在的全部理由就是这个信号。
    # 所以选题类待办标成建议(blocking=False):它出现在待办清单里,但不抢导轨。
    with_todo = {t["step"] for t in todos}
    blocking = {t["step"] for t in todos if t.get("blocking")}
    here = next(
        (s.key for s in STEPS if s.key in blocking),
        # 没有任何挡路的 → 停在最后一步:该做的都做完了。
        STEP_PUBLISH,
    )

    values = {
        STEP_PICK: f"{unpicked + no_questions} 件待挑",
        STEP_GENERATE: f"{counts['generated']} 篇已写",
        STEP_REVIEW: f"{pending} 篇在等" if pending else "都审完了",
        STEP_PUBLISH: (
            f"{to_publish} 篇待发"
            if to_publish
            else (f"{drafts} 篇草稿待你发" if drafts else f"{counts['live']} 篇在线上")
        ),
    }
    return {
        "steps": [
            {
                "key": step.key,
                "title": step.title,
                "who": step.who,
                "value": values[step.key],
                "here": step.key == here,
                "done": step.key not in with_todo,
            }
            for step in STEPS
        ],
        "todos": todos,
        "counts": counts,
    }


__all__ = [
    "PICK_SCORE_FLOOR",
    "STEPS",
    "STEP_GENERATE",
    "STEP_PICK",
    "STEP_PUBLISH",
    "STEP_REVIEW",
    "build_overview",
    "failed_jobs",
]
