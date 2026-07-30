"""B2B:样品抵扣台账 + 发货单据 + 订单阶段。

三件都是**补欠账**,不是新功能:
- 样品抵扣:小窗/批发页/图册/开发信**四处**都承诺了"样品费全额抵扣首单",
  可系统里没有任何地方记账,第三个客户就开始虚。
- 商业发票/装箱单:批发页上写了"every order 提供 commercial invoice、
  packing list 和运输单据",而只有 PI。
- 订单阶段:PI 开出去之后没有下文,定金到没到全靠脑子记。

Revision ID: 20260729_15_b2b_orders_and_credits
Revises: 20260729_14_b2b_documents
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_15_b2b_orders_and_credits"
down_revision: str | Sequence[str] | None = "20260729_14_b2b_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_sample_credits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_email", sa.String(length=320), nullable=False),
        sa.Column("buyer_company", sa.String(length=200), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("consumed_document_id", sa.Uuid(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_b2b_sample_credits_email", "b2b_sample_credits", ["buyer_email"]
    )

    op.add_column(
        "b2b_documents", sa.Column("source_document_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "b2b_documents",
        sa.Column(
            "stage",
            sa.String(length=20),
            nullable=False,
            server_default="quoted",
        ),
    )
    op.add_column("b2b_documents", sa.Column("carton_count", sa.Integer(), nullable=True))
    op.add_column(
        "b2b_documents", sa.Column("gross_weight_kg", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "b2b_documents", sa.Column("net_weight_kg", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "b2b_documents", sa.Column("sample_credit", sa.Numeric(12, 2), nullable=True)
    )

    # doc_type 放开到三种。CHECK 约束改不了,只能删了重建。
    op.drop_constraint("ck_b2b_documents_doc_type", "b2b_documents", type_="check")
    op.create_check_constraint(
        "ck_b2b_documents_doc_type",
        "b2b_documents",
        "doc_type IN ('proforma_invoice', 'commercial_invoice', 'packing_list')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_b2b_documents_doc_type", "b2b_documents", type_="check")
    op.create_check_constraint(
        "ck_b2b_documents_doc_type",
        "b2b_documents",
        "doc_type IN ('proforma_invoice')",
    )
    for column in (
        "sample_credit",
        "net_weight_kg",
        "gross_weight_kg",
        "carton_count",
        "stage",
        "source_document_id",
    ):
        op.drop_column("b2b_documents", column)
    op.drop_index("ix_b2b_sample_credits_email", table_name="b2b_sample_credits")
    op.drop_table("b2b_sample_credits")
