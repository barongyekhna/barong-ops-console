"""B2B store types + store-type↔category mapping.

店型成为 B2B 的主键:挖客户、发信、出图册全部按店型走,类目退化成"这个店型
能拿到哪些货"的实现细节。见 store_types/models.py 的模块注释。

迁移里顺带把已存在的四个店型(来自 b2b_prospect_queries 的 distinct store_type)
建出来,并按当前目录挂上类目前缀,免得上线后是一片空白。

Revision ID: 20260728_03_b2b_store_types
Revises: 20260728_02_geo_permissions
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_03_b2b_store_types"
down_revision: str | Sequence[str] | None = "20260728_02_geo_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 店型 -> 默认吃哪些类目前缀。按用户当前目录写的:
# - 捏捏球(Toys & Games > Toys > Executive Toys)对礼品店和玩具店都成立
# - 露营花洒(Sporting Goods > ...)对户外店和房车店都成立
# 以后加五金/家居,在界面上挂前缀即可,不改代码。
_DEFAULT_CATEGORIES: dict[str, list[list[str]]] = {
    "gift_shop": [["Toys & Games"]],
    "outdoor_store": [["Sporting Goods"]],
    "vanlife_store": [["Sporting Goods"]],
    "pet_boutique": [],
}
_SORT_ORDER = {
    "gift_shop": 10,
    "outdoor_store": 20,
    "pet_boutique": 30,
    "vanlife_store": 40,
}


def upgrade() -> None:
    op.create_table(
        "b2b_store_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column(
            "outreach_status",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key", name="uq_b2b_store_types_key"),
        sa.CheckConstraint(
            "outreach_status IN ('idle', 'active', 'paused', 'retired')",
            name="ck_b2b_store_types_outreach_status",
        ),
    )
    op.create_index(
        "ix_b2b_store_types_outreach_status",
        "b2b_store_types",
        ["outreach_status"],
    )

    op.create_table(
        "b2b_store_type_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_type_id", sa.Uuid(), nullable=False),
        sa.Column("category_prefix", sa.JSON(), nullable=False),
        sa.Column("category_key", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["store_type_id"],
            ["b2b_store_types.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "store_type_id",
            "category_key",
            name="uq_b2b_store_type_categories_pair",
        ),
    )
    op.create_index(
        "ix_b2b_store_type_categories_store",
        "b2b_store_type_categories",
        ["store_type_id"],
    )

    _seed_from_existing_queries()


def _seed_from_existing_queries() -> None:
    """把已有查询模板里的店型建成正式记录,并挂上默认类目。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "b2b_prospect_queries" not in inspector.get_table_names():
        return

    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT store_type, store_type_label "
            "FROM b2b_prospect_queries ORDER BY store_type"
        )
    ).fetchall()

    for key, label in rows:
        store_type_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO b2b_store_types "
                "(id, key, label, outreach_status, sort_order) "
                "VALUES (:id, :key, :label, 'idle', :sort_order) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
                "id": store_type_id,
                "key": key,
                "label": label,
                "sort_order": _SORT_ORDER.get(key, 100),
            },
        )
        for prefix in _DEFAULT_CATEGORIES.get(key, []):
            bind.execute(
                sa.text(
                    "INSERT INTO b2b_store_type_categories "
                    "(id, store_type_id, category_prefix, category_key) "
                    "VALUES (:id, :store_type_id, :category_prefix, "
                    ":category_key) "
                    "ON CONFLICT (store_type_id, category_key) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "store_type_id": store_type_id,
                    "category_prefix": json.dumps(prefix),
                    "category_key": " > ".join(prefix),
                },
            )


def downgrade() -> None:
    op.drop_index(
        "ix_b2b_store_type_categories_store",
        table_name="b2b_store_type_categories",
    )
    op.drop_table("b2b_store_type_categories")
    op.drop_index(
        "ix_b2b_store_types_outreach_status", table_name="b2b_store_types"
    )
    op.drop_table("b2b_store_types")
