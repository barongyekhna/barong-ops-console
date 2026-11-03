"""K:放行词表 k_brand_allow_terms(11-03 老板定)。

老板确认「用在我们商品上不是别人的牌子」的普通词,全站所有品牌/商标检查都认(brand_allow.py)。
起因是熊猫造型的商品被「panda」当成别人的商标一再挡掉;老板原话:「不能因为有一家公司叫panda，就不让我用这个词
形容我的产品了……他的panda商标只限餐饮类和我一点关系都没有」。上线即放进 panda 一条(备注写老板原话)。

无 org_id 列(独立站一个,全站共用)。to_regclass 幂等;种子 ON CONFLICT DO NOTHING。

Revision ID: 20261103_02_k_brand_allow_terms
Revises: 20261103_01_suqinghe_gsc_pages
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261103_02_k_brand_allow_terms"
down_revision = "20261103_01_suqinghe_gsc_pages"
branch_labels = None
depends_on = None

TABLE = "k_brand_allow_terms"
SEED_NOTE = (
    "11-03 老板定:「不能因为有一家公司叫panda，就不让我用这个词形容我的产品了。我的产品是真实的panda造型的。"
    "他的panda商标只限餐饮类和我一点关系都没有」"
)


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("term", sa.String(length=120), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("term", name="uq_k_brand_allow_terms_term"),
        )
    conn.exec_driver_sql(
        f"INSERT INTO {TABLE} (id, term, note) VALUES (gen_random_uuid(), 'panda', %(note)s) ON CONFLICT (term) DO NOTHING",
        {"note": SEED_NOTE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
