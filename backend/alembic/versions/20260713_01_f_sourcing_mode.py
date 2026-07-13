"""F 富化运行加 1688 找货段 — mode / candidates_found / alibaba_calls

full = 爬词+1688找货（一键全链）；keywords_only = 纯爬词（历史行为）；
sourcing_only = 只补货源（详情面板单类目按钮）。

Revision ID: 20260713_01_f_sourcing_mode
Revises: 20260712_02_f_series_enrichment
Create Date: 2026-07-13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_01_f_sourcing_mode"
down_revision: str | Sequence[str] | None = "20260712_02_f_series_enrichment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "f_enrichment_runs"


def upgrade() -> None:
    op.add_column(
        T,
        sa.Column(
            "mode",
            sa.String(length=20),
            nullable=False,
            server_default="keywords_only",
        ),
    )
    op.add_column(
        T,
        sa.Column(
            "candidates_found", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        T,
        sa.Column("alibaba_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_f_runs_valid_mode",
        T,
        "mode IN ('full', 'keywords_only', 'sourcing_only')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_f_runs_valid_mode", T, type_="check")
    op.drop_column(T, "alibaba_calls")
    op.drop_column(T, "candidates_found")
    op.drop_column(T, "mode")
