"""Webhook 登记簿（模块控制页 Webhook 标签）。

各系列（P/GMC/SEO…）用到的 n8n webhook 在此登记备查：来源系列、webhook URL、
回传（respond/callback）URL、对应 n8n 工作流名。只做记录 —— 真实调用仍走
各系列自己的配置（如 P 的 env N8N_P_UPLOAD_WEBHOOK），此表不参与调用链。

Revision ID: 20260711_02_webhook_registry
Revises: 20260711_01_c19_control_core
Create Date: 2026-07-11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260711_02_webhook_registry"
down_revision: str | Sequence[str] | None = "20260711_01_c19_control_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "webhook_registry_entries"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("series", sa.String(length=32), nullable=False),
        sa.Column("workflow_name", sa.String(length=255), nullable=False),
        sa.Column("webhook_url", sa.String(length=1024), nullable=False),
        sa.Column("respond_url", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            nullable=False,
        ),
    )
    op.create_index("idx_webhook_registry_series", TABLE, ["series"])


def downgrade() -> None:
    op.drop_index("idx_webhook_registry_series", table_name=TABLE)
    op.drop_table(TABLE)
