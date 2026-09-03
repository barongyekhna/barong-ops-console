"""内容自检:**声称做完了,产物却不存在**。

由来(2026-08-01):用户问「geo/seo/内链网是不是都做完了」,我一条条查库才发现
SEO 选题 ``e52c512c`` 被标成 ``written``,库里却一篇文章都没有——07-30 那个
``item_type`` bug 的残留:文章被回滚了,选题状态和 job 状态却各自提交了。

后果不是"少一篇文章",而是**它永远不会再被派出去生成**:控制台以为写过了。
这种记录不会报错、不会变红、不会出现在任何列表里,只会静静地少一篇内容。

**当时没有任何东西能发现这个矛盾。** 那次的 bug 早修了(现在是一个事务原子
提交),但"没人看着"这件事本身才是缺口——所以这里加的是**看着的机器**,
不是给那一行数据打补丁。

同一个形状在 GEO 侧同样存在:簇标成 ready/approved 却零条目。所以判据写成
声明式的一张表,加新的内容类型时加一行,不用再写一遍逻辑。

这和 ``external_side_effect_verify`` 那条死规矩是同一件事的两面:那条管
"写出去了没有",这条管"写进来了没有"。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import normalize_scope_context
from ...services.data_isolation import SKIP_ORG_DATA_ISOLATION

logger = logging.getLogger(__name__)

# 表名/列名是**代码里写死的常量**,不是用户输入。但它们仍然会被拼进 SQL,
# 所以照 html_blocks 的 class 白名单一样过一道——白名单的成本是零,
# 而"这里永远不会有用户输入"这个前提哪天被人打破时,它是唯一的拦网。
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class ConsistencyError(RuntimeError):
    """判据本身写错了(表名/列名非法)。这是程序员错误,不是数据问题。"""


@dataclass(frozen=True)
class ProductionCheck:
    """一条「父记录声称有产物」的判据。

    label       人话名字,直接显示给用户
    parent      父表(选题 / 簇)
    child       产物表(文章)
    child_fk    产物表里指回父记录的列
    done_status 表示"已完成"的状态值;处于这些状态却没有产物 = 卡死
    reset_to    复位成哪个状态,让它重新可以被派单
    name_column 拿来显示给人看的那一列
    """

    label: str
    parent: str
    child: str
    child_fk: str
    done_status: tuple[str, ...]
    reset_to: str
    name_column: str

    def __post_init__(self) -> None:
        for value in (
            self.parent,
            self.child,
            self.child_fk,
            self.name_column,
        ):
            if not _IDENT_RE.match(value):
                raise ConsistencyError(f"非法标识符:{value!r}")


CHECKS: tuple[ProductionCheck, ...] = (
    ProductionCheck(
        label="SEO 选题",
        parent="seo_topics",
        child="seo_content_items",
        child_fk="topic_id",
        done_status=("written",),
        # 回到 picked 而不是 candidate:这个选题**是人挑过的**,复位不该把
        # 那次决定也一起抹掉,否则用户得重新在雷达里找一遍。
        reset_to="picked",
        name_column="keyword",
    ),
    ProductionCheck(
        label="GEO 簇",
        parent="geo_content_clusters",
        child="geo_content_items",
        child_fk="cluster_id",
        # 簇一旦离开 draft/generating 就等于宣称"有内容了"。
        done_status=("ready", "needs_review", "approved"),
        reset_to="draft",
        name_column="title",
    ),
)


def find_stranded(
    db: Session,
    *,
    checks: tuple[ProductionCheck, ...] = CHECKS,
    failed_labels: list[str] | None = None,
    scope: Any | None = None,
) -> list[dict[str, Any]]:
    """所有「标了完成却没有产物」的记录。**只读,不出网,不改任何东西。**

    一条判据查不动(比如表还没建)不该让整个面板打不开——单条吞掉并记日志。

    **但吞掉不等于当作没事**:2026-08-31 体检发现这几条判据被 C18G 全部拒掉
    (裸 SQL 不带 org_id),于是每次都返回空列表,页面渲染成「✓ 内容自检 无异常」——
    一次都没跑成,却报了绿灯。这违反「事实检查必须 fail-closed」的死规矩。
    调用方传 ``failed_labels`` 进来就能拿到跑挂的判据名,据此把结论标成
    「没跑成」而不是「没问题」。
    """
    out: list[dict[str, Any]] = []
    for check in checks:
        try:
            rows = db.execute(
                text(
                    f"""
                    SELECT p.id, p.{check.name_column} AS display_name, p.status
                    FROM {check.parent} p
                    WHERE p.status = ANY(:done)
                      AND p.workspace_key = :ws
                      AND NOT EXISTS (
                          SELECT 1 FROM {check.child} c
                          WHERE c.{check.child_fk} = p.id
                      )
                    ORDER BY p.created_at
                    """
                ),
                {"done": list(check.done_status), "ws": normalize_scope_context(scope).workspace_key},
                execution_options=SKIP_ORG_DATA_ISOLATION,
            ).mappings().all()
        except Exception:  # noqa: BLE001 - 一条判据坏掉不该毁掉整块面板
            logger.exception("consistency check failed: %s", check.label)
            if failed_labels is not None:
                failed_labels.append(check.label)
            continue
        for row in rows:
            out.append(
                {
                    "kind": check.parent,
                    "label": check.label,
                    "id": str(row["id"]),
                    "name": str(row["display_name"] or "")[:200],
                    "status": str(row["status"]),
                    "reset_to": check.reset_to,
                    "reason": (
                        f"{check.label}「{str(row['display_name'] or '')[:40]}」"
                        f"标成了「{row['status']}」，但一篇内容都没有"
                    ),
                }
            )
    return out


def reset_stranded(
    db: Session,
    *,
    kind: str,
    record_ids: list[str],
    checks: tuple[ProductionCheck, ...] = CHECKS,
    scope: Any | None = None,
) -> int:
    """把卡死的记录复位,让它重新能被派单。

    **只复位真的卡死的那些**——``NOT EXISTS`` 条件原样带进 UPDATE。否则一次
    误点就可能把正常的、已经有文章的记录也打回去,让人重复生成一遍(花钱)。
    这是"读一遍再写"和"写的时候自己再验一次"的区别,后者没有竞态。
    """
    check = next((c for c in checks if c.parent == kind), None)
    if check is None:
        raise ConsistencyError(f"未知的自检类型:{kind!r}")
    ids = [str(i).strip() for i in record_ids if str(i).strip()]
    if not ids:
        return 0
    result = db.execute(
        text(
            f"""
            UPDATE {check.parent} p
            SET status = :reset_to
            WHERE p.id = ANY(CAST(:ids AS uuid[]))
              AND p.workspace_key = :ws
              AND p.status = ANY(:done)
              AND NOT EXISTS (
                  SELECT 1 FROM {check.child} c
                  WHERE c.{check.child_fk} = p.id
              )
            """
        ),
        {
            "reset_to": check.reset_to,
            "ids": ids,
            "done": list(check.done_status),
            "ws": normalize_scope_context(scope).workspace_key,
        },
        execution_options=SKIP_ORG_DATA_ISOLATION,
    )
    db.commit()
    return result.rowcount or 0


__all__ = [
    "CHECKS",
    "ConsistencyError",
    "ProductionCheck",
    "find_stranded",
    "reset_stranded",
]
