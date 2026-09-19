"""RD 系列 · 客户端诊断黑匣子 ``rd_client_traces``。

2026-09-18 真机首测失败:对方同意后,发起端再没有任何请求到达服务器,服务器侧无从
知道它卡在哪一步。两端页面从此把建连的每一步先记在本地、事后补传到这张表。

纯新增一张表,不动任何现有表。与 RD 其余四张表一样刻意不带 ``org_id``。

Revision ID: 20260918_03_rd_client_traces
Revises: 20260918_02_amz_actions_ledger
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_03_rd_client_traces"
down_revision: str | Sequence[str] | None = "20260918_02_amz_actions_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rd_client_traces",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("client_label", sa.String(length=120), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("step", sa.String(length=48), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("client_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id", "seq", name="uq_rd_client_traces_client_seq"
        ),
    )
    op.create_index(
        "ix_rd_client_traces_session", "rd_client_traces", ["session_id", "client_at"]
    )
    op.create_index(
        "ix_rd_client_traces_user_received",
        "rd_client_traces",
        ["user_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rd_client_traces_user_received", table_name="rd_client_traces")
    op.drop_index("ix_rd_client_traces_session", table_name="rd_client_traces")
    op.drop_table("rd_client_traces")
