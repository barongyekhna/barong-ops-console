"""F 类目体验 — 谷歌树中文名 + 类目产品画像缓存

k_category_google 加 name_zh（谷歌官方 zh-CN taxonomy 按 ID 对齐灌入，
见 scripts/seed_google_taxonomy_zh.py）；f_category_profiles 缓存 DeepSeek
生成的「这个类目通常包含哪些产品」中英文画像（一次生成永久缓存）。

Revision ID: 20260713_03_f_category_experience
Revises: 20260713_02_w_shipping_hub
Create Date: 2026-07-13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_03_f_category_experience"
down_revision: str | Sequence[str] | None = "20260713_02_w_shipping_hub"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILES = "f_category_profiles"


def upgrade() -> None:
    op.add_column(
        "k_category_google",
        sa.Column("name_zh", sa.String(length=512), nullable=True),
    )

    op.create_table(
        PROFILES,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("products_json", sa.JSON(), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=50),
            nullable=False,
            server_default="deepseek",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("category_id", name="uq_f_profiles_category"),
    )
    op.create_index("ix_f_profiles_category", PROFILES, ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_f_profiles_category", table_name=PROFILES)
    op.drop_table(PROFILES)
    op.drop_column("k_category_google", "name_zh")
