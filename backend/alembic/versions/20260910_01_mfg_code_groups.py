"""M 系列 · 编码组(成品系列 / 物料大类)+ 主档挂组。

成品编码 = 系列码-三位流水(TBL-001),物料编码 = 大类码-四位流水(PK-0001),
流水按组各自发号,取号 FOR UPDATE。老数据 group_id 为空(手填编码)照旧有效。

Revision ID: 20260910_01_mfg_code_groups
Revises: 20260906_02_sm_social_permissions
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260910_01_mfg_code_groups"
down_revision: str | Sequence[str] | None = "20260906_02_sm_social_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mfg_code_groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("next_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "factory_org_id", "code", name="uq_mfg_code_groups_factory_org_id"
        ),
        sa.CheckConstraint(
            "kind IN ('part', 'product')", name="ck_mfg_code_groups_kind"
        ),
    )
    op.create_index(
        "ix_mfg_code_groups_factory_kind", "mfg_code_groups", ["factory_org_id", "kind"]
    )
    op.add_column(
        "mfg_items",
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_code_groups.id",
                ondelete="SET NULL",
                name="fk_mfg_items_group_id_mfg_code_groups",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_mfg_items_group_id", "mfg_items", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_mfg_items_group_id", table_name="mfg_items")
    op.drop_constraint(
        "fk_mfg_items_group_id_mfg_code_groups", "mfg_items", type_="foreignkey"
    )
    op.drop_column("mfg_items", "group_id")
    op.drop_index("ix_mfg_code_groups_factory_kind", table_name="mfg_code_groups")
    op.drop_table("mfg_code_groups")
