"""工艺事实库:全站共享的可核知识资产,带版本与引用追踪。

用户明确"工艺事实会不断更新",这决定了它不能是一张能就地改写的表:今天的文章
引用了某条事实,明天工艺改了,文章就悄悄变成错的。整套内容系统建立在"绝不编造"
上,而**过期的真话和编造一样有害**——甚至更危险,因为它带着可信的外表,没有任何
输出护栏会报警。

三张表:事实本体(带版本号)、历史快照(改了什么/谁改的/为什么)、引用台账(哪篇
内容用了哪条事实的哪个版本)。`usage.fact_version < fact.version` 即为过期。

放在 content_core 而非 seo_series:GEO 指南会引用工艺,B2B 批发页更要靠它证明
有真工厂——谁都可能引用。

Revision ID: 20260729_10_craft_facts
Revises: 20260729_09_geo_item_wp_status
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_10_craft_facts"
down_revision: str | Sequence[str] | None = "20260729_09_geo_item_wp_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS = "default_independent_store"
_BC = "independent_store"
_SM = "adapter_pending"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "craft_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_key", sa.String(length=128), nullable=False, server_default=_WS),
        sa.Column("business_context", sa.String(length=64), nullable=False, server_default=_BC),
        sa.Column("scope_mode", sa.String(length=32), nullable=False, server_default=_SM),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("value", sa.String(length=64), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("product_ids_json", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint("status IN ('draft', 'approved', 'retired')",
                           name="ck_craft_facts_valid_status"),
        sa.CheckConstraint("version >= 1", name="ck_craft_facts_version_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_craft_facts"),
    )
    op.create_index("ix_craft_facts_topic", "craft_facts", ["topic"])
    op.create_index("ix_craft_facts_status", "craft_facts", ["status"])

    op.create_table(
        "craft_fact_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by_user_id", sa.BigInteger(), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name="pk_craft_fact_revisions"),
        sa.ForeignKeyConstraint(["fact_id"], ["craft_facts.id"],
                                name="fk_craft_fact_revisions_fact_id"),
        sa.UniqueConstraint("fact_id", "version", name="uq_craft_fact_revision"),
    )
    op.create_index("ix_craft_fact_revisions_fact", "craft_fact_revisions", ["fact_id"])

    op.create_table(
        "content_fact_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_kind", sa.String(length=32), nullable=False),
        sa.Column("content_id", sa.String(length=64), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("fact_version", sa.Integer(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name="pk_content_fact_usage"),
        sa.ForeignKeyConstraint(["fact_id"], ["craft_facts.id"],
                                name="fk_content_fact_usage_fact_id"),
        sa.UniqueConstraint("content_kind", "content_id", "fact_id",
                            name="uq_content_fact_usage"),
    )
    op.create_index("ix_content_fact_usage_fact", "content_fact_usage", ["fact_id"])
    op.create_index("ix_content_fact_usage_content", "content_fact_usage",
                    ["content_kind", "content_id"])


def downgrade() -> None:
    op.drop_table("content_fact_usage")
    op.drop_table("craft_fact_revisions")
    op.drop_table("craft_facts")
