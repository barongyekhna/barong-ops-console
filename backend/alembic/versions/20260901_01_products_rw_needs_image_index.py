"""给 products_rw 的「待补图」查询加部分索引。

2026-09-01：`r-w-keepa-daemon` 每一轮都以 `statement timeout` 失败。
它的取单查询是：

    SELECT asin, title, image_url, features FROM products_rw
    WHERE image_url IS NULL OR image_url = '' OR image_url LIKE '%/images/P/%'
       OR COALESCE(features->>'image_candidates','') LIKE '%/images/P/%'
    ORDER BY updated_at DESC NULLS LAST, asin ASC LIMIT 12

四个 OR 条件里有两个 `LIKE '%…%'` 和一个 jsonb 提取，**没有任何普通索引能服务它**。
实测 `EXPLAIN ANALYZE`：扫描 98,264 行、耗时 **34.2 秒**，而只为找出 **1 行**；
而这些 worker 的连接上 `statement_timeout` 是 8 秒 —— 于是它每一轮都必挂。

这正是体检报告里那条「R-A worker 崩溃后死了一个月」的同族问题：抢单查询本身跑不完，
而自愈逻辑依赖同一条查询，一起死。

部分索引（partial index）恰好适合这种「绝大多数行不符合条件」的场景：
只索引符合谓词的那极少数行（当前是 1 行），体积极小，且能直接服务 ORDER BY。

谓词必须与查询里的 WHERE **逐字一致**，否则规划器用不上它。

Revision ID: 20260901_01_products_rw_needs_image_index
Revises: 20260828_01_mcp_access_tokens
"""

from __future__ import annotations

from alembic import op

revision = "20260901_01_products_rw_needs_image_index"
down_revision = "20260828_01_mcp_access_tokens"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_products_rw_needs_image"

# 与 r_system_v2 里那条取单查询的 WHERE 逐字一致。
# 注意 %% —— exec_driver_sql 走 psycopg 的参数化通道，裸 % 会被当成占位符
# （实测报 "only '%s', '%b', '%t' are allowed as placeholders, got '%/'"）。
# 索引落库后谓词里是单个 %，与查询的 WHERE 逐字一致。
PREDICATE = (
    "image_url IS NULL "
    "OR image_url = '' "
    "OR image_url LIKE '%%/images/P/%%' "
    "OR COALESCE(features->>'image_candidates', '') LIKE '%%/images/P/%%'"
)


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    # products_rw 由 r_system_v2 的建表脚本维护，不在 ORM 里；库里没有就跳过。
    if not _table_exists(conn, "products_rw"):
        return
    conn.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
        f"ON products_rw (updated_at DESC NULLS LAST, asin ASC) "
        f"WHERE {PREDICATE}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(f"DROP INDEX IF EXISTS {INDEX_NAME}")
