"""簇的归属守卫——保证不同产品进对簇,而且**簇之间不会互相竞争**。

## 归属是怎么定的

产品的 ``google_product_category`` 与簇的 ``google_category_id`` **精确字符串
匹配**。没有 AI、没有模糊匹配、没有人工判断——所以"同类目的产品进同一个簇、
不同类目的进不同簇"是**结构保证**,不是靠谁记得。

## 但精确匹配防不住的那件事

谷歌类目是**树**。`Executive Toys`(父)底下有 `Magnet Toys`(子)。
精确匹配只认相等,所以这两个类目会各自开一个簇——而它们写的是**同一片话题**,
两个簇互相抢同一批词。这正是「一类目一簇」要防的自我竞争,却从树结构漏进来。

所以真正要守的不是"必须挂叶子"(那是错的:谷歌树里根本没有"捏捏"这个叶子,
`Executive Toys` 这个非叶子恰恰是最准的节点,强制叶子反而逼出错误归类),
而是:**任意两个簇的类目之间,不能有祖先-后代关系。**

## 三种情形怎么处理

- **完全相同** → 挂上去(本来就该同簇)
- **已有祖先簇** → 挂到祖先簇上。它已经在写这片话题了,再开一个更细的簇
  就是把同一批词拆成两半自己打自己。真要细分,等那个子类目产品够多、
  由人明确决定拆。
- **已有后代簇** → **拒绝建父簇**,报清楚让人来判。自动合并会动到已发布内容,
  自动跳过又会让产品无处可去——这两种都不该由代码替人决定。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from .models import GeoContentCluster

logger = logging.getLogger(__name__)


class ClusterOverlapError(RuntimeError):
    """建这个簇会和已有的簇抢同一片话题。"""


def category_ancestors(db: Session, google_id: str) -> list[str]:
    """从自己往上到根的所有类目 id(不含自己)。"""
    if not str(google_id or "").strip():
        return []
    try:
        rows = db.execute(
            sql_text(
                """
                WITH RECURSIVE up AS (
                    SELECT id, parent_id FROM k_category_google WHERE id = :gid
                    UNION ALL
                    SELECT c.id, c.parent_id
                    FROM k_category_google c JOIN up ON c.id = up.parent_id
                )
                SELECT id FROM up WHERE id <> :gid
                """
            ),
            {"gid": str(google_id)},
        ).all()
    except Exception:  # noqa: BLE001 - 类目树读不到就当没有祖先,别炸
        logger.exception("category ancestor lookup failed for %s", google_id)
        return []
    return [str(r[0]) for r in rows]


def category_descendants(db: Session, google_id: str) -> list[str]:
    """自己底下的所有类目 id(不含自己)。"""
    if not str(google_id or "").strip():
        return []
    try:
        rows = db.execute(
            sql_text(
                """
                WITH RECURSIVE down AS (
                    SELECT id FROM k_category_google WHERE id = :gid
                    UNION ALL
                    SELECT c.id
                    FROM k_category_google c JOIN down ON c.parent_id = down.id
                )
                SELECT id FROM down WHERE id <> :gid
                """
            ),
            {"gid": str(google_id)},
        ).all()
    except Exception:  # noqa: BLE001
        logger.exception("category descendant lookup failed for %s", google_id)
        return []
    return [str(r[0]) for r in rows]


def _scoped_clusters(db: Session, scope_context: Any) -> list[GeoContentCluster]:
    return list(
        db.execute(
            select(GeoContentCluster)
            .where(
                GeoContentCluster.workspace_key == scope_context.workspace_key,
                GeoContentCluster.business_context == scope_context.business_context,
                GeoContentCluster.scope_mode == scope_context.scope_mode,
                GeoContentCluster.status != "archived",
            )
            .order_by(GeoContentCluster.created_at)
        ).scalars()
    )


def resolve_cluster_for_category(
    db: Session, *, google_category_id: str, scope_context: Any
) -> tuple[str, GeoContentCluster | None]:
    """(关系, 簇)。关系 ∈ exact / ancestor / descendant / none。

    - ``exact`` / ``ancestor`` → 直接挂上去,这个簇已经拥有这片话题
    - ``descendant`` → 调用方必须拒绝建父簇(见模块文档)
    - ``none`` → 可以新建
    """
    google_id = str(google_category_id or "").strip()
    if not google_id:
        return "none", None

    clusters = _scoped_clusters(db, scope_context)
    by_category: dict[str, GeoContentCluster] = {}
    for cluster in clusters:
        key = str(cluster.google_category_id or "").strip()
        if key and key not in by_category:
            by_category[key] = cluster

    if google_id in by_category:
        return "exact", by_category[google_id]

    # 祖先优先:越近的祖先越贴切,而 ancestors 是自底向上的顺序。
    for ancestor in category_ancestors(db, google_id):
        if ancestor in by_category:
            return "ancestor", by_category[ancestor]

    for descendant in category_descendants(db, google_id):
        if descendant in by_category:
            return "descendant", by_category[descendant]

    return "none", None


def assert_no_overlapping_cluster(
    db: Session, *, google_category_id: str, scope_context: Any
) -> None:
    """**两个方向都拦**——手工建簇时,祖先和后代一样是自我竞争。

    2026-07-30 实测抓到我自己的漏:原来只拦了"要建父簇、底下已有子簇"。
    反过来"要建子簇、上面已有父簇"照样建得出来,而它一样和父簇抢同一批词。
    自动挂簇那条路(P 上架)对祖先是**吸收**(挂到父簇上,合理);
    但手工建簇是人明确说"我要一个新簇",这时候静默改挂到别的簇上更吓人——
    该做的是拦住并说清楚。
    """
    relation, cluster = resolve_cluster_for_category(
        db, google_category_id=google_category_id, scope_context=scope_context
    )
    if cluster is None or relation in ("none", "exact"):
        return
    where = cluster.category_path or cluster.google_category_id
    if relation == "descendant":
        raise ClusterOverlapError(
            f"这个类目**底下**已经有一个更细的话题簇「{cluster.title}」（{where}）"
            "在写同一片话题。再建一个更粗的簇，两边会抢同一批词、权重对半分。\n"
            "怎么办：要么把产品归到那个更细的类目下，要么先归档那个簇再建这个"
            "——两种都得你来定，代码不替你选。"
        )
    raise ClusterOverlapError(
        f"这个类目**上面**已经有一个更粗的话题簇「{cluster.title}」（{where}）"
        "在写同一片话题。再建一个更细的簇，两边会抢同一批词、权重对半分。\n"
        "怎么办：把产品挂到那个簇里（同类目产品本来就该共用一套内容，"
        "差异化产品用「产品专属文章」），或者先归档那个簇再建这个。"
    )


# 旧名保留:P 自动挂簇只关心"底下有没有子簇"这一个方向。
def assert_no_descendant_cluster(
    db: Session, *, google_category_id: str, scope_context: Any
) -> None:
    relation, cluster = resolve_cluster_for_category(
        db, google_category_id=google_category_id, scope_context=scope_context
    )
    if relation != "descendant" or cluster is None:
        return
    assert_no_overlapping_cluster(
        db, google_category_id=google_category_id, scope_context=scope_context
    )


def overlapping_cluster_pairs(db: Session, scope_context: Any) -> list[dict[str, Any]]:
    """诊断:现存的簇里,哪些对存在祖先-后代关系。

    历史数据可能已经有重叠(守卫是后加的)。这个清单让它显形,而不是等到
    排名被自己拖下去才发现。
    """
    clusters = [c for c in _scoped_clusters(db, scope_context) if c.google_category_id]
    out: list[dict[str, Any]] = []
    for cluster in clusters:
        google_id = str(cluster.google_category_id)
        descendants = set(category_descendants(db, google_id))
        for other in clusters:
            if other.id == cluster.id:
                continue
            if str(other.google_category_id) in descendants:
                out.append(
                    {
                        "parent_cluster": cluster.title,
                        "parent_category": cluster.category_path,
                        "child_cluster": other.title,
                        "child_category": other.category_path,
                        "why": "父簇和子簇写同一片话题，会互相抢词",
                    }
                )
    return out


__all__ = [
    "ClusterOverlapError",
    "assert_no_descendant_cluster",
    "assert_no_overlapping_cluster",
    "category_ancestors",
    "category_descendants",
    "overlapping_cluster_pairs",
    "resolve_cluster_for_category",
]
