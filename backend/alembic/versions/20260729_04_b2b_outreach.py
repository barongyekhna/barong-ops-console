"""B2B outreach: email templates, draft box, and the AI-written opening line.

草稿箱刻意**不带发送能力**——验证期前 30 封必须用户亲手发,目的是测出哪句话
有人回。见 outreach/models.py 的模块注释。

Revision ID: 20260729_04_b2b_outreach
Revises: 20260729_03_geo_backlink
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_04_b2b_outreach"
down_revision: str | Sequence[str] | None = "20260729_03_geo_backlink"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 开发信首句:AI 在筛选时顺手写的,不额外花一次调用。
    op.add_column(
        "b2b_prospects",
        sa.Column("personal_line", sa.String(length=500), nullable=True),
    )

    op.create_table(
        "b2b_email_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        # 空串 = 全店型通用。Postgres 的 UNIQUE 对 NULL 不去重,所以用空串。
        sa.Column(
            "store_type",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "is_builtin", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.UniqueConstraint(
            "kind", "language", "store_type",
            name="uq_b2b_email_templates_combo",
        ),
        sa.CheckConstraint(
            "kind IN ('first_touch', 'follow_up', 'reply_pricing', "
            "'reply_moq', 'reply_sample', 'reply_oem', 'reply_no')",
            name="ck_b2b_email_templates_kind",
        ),
    )
    op.create_index(
        "ix_b2b_email_templates_kind", "b2b_email_templates", ["kind"]
    )

    op.create_table(
        "b2b_email_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="draft"
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "prospect_id", "kind", name="uq_b2b_email_drafts_prospect_kind"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'sent', 'skipped')",
            name="ck_b2b_email_drafts_status",
        ),
    )
    op.create_index(
        "ix_b2b_email_drafts_status", "b2b_email_drafts", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_b2b_email_drafts_status", table_name="b2b_email_drafts")
    op.drop_table("b2b_email_drafts")
    op.drop_index(
        "ix_b2b_email_templates_kind", table_name="b2b_email_templates"
    )
    op.drop_table("b2b_email_templates")
    op.drop_column("b2b_prospects", "personal_line")
