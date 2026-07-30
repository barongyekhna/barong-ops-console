"""B2B 单据(形式发票 PI)。

外贸收钱的动作是买家拿着 PI 去银行电汇定金。没有这张纸,客户说"我要了"
之后就卡住——漏斗最后一节是断的。

内容整份快照(items_json / terms_json):单据一旦发出去就是对外承诺的凭证,
批发价过两天调了、条款改了,已经发出去的那张必须还是当时那个样子。

Revision ID: 20260729_14_b2b_documents
Revises: 20260729_13_b2b_suppressions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_14_b2b_documents"
down_revision: str | Sequence[str] | None = "20260729_13_b2b_suppressions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("buyer_company", sa.String(length=200), nullable=False),
        sa.Column("buyer_contact", sa.String(length=120), nullable=True),
        sa.Column("buyer_email", sa.String(length=320), nullable=True),
        sa.Column("buyer_address", sa.Text(), nullable=True),
        sa.Column("ship_to", sa.Text(), nullable=True),
        sa.Column("items_json", postgresql.JSONB(), nullable=False),
        sa.Column("terms_json", postgresql.JSONB(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("freight", sa.Numeric(12, 2), nullable=True),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "doc_type IN ('proforma_invoice')", name="ck_b2b_documents_doc_type"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'void')",
            name="ck_b2b_documents_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_b2b_documents_number", "b2b_documents", ["number"], unique=True)
    op.create_index("ix_b2b_documents_created_at", "b2b_documents", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_b2b_documents_created_at", table_name="b2b_documents")
    op.drop_index("ix_b2b_documents_number", table_name="b2b_documents")
    op.drop_table("b2b_documents")
