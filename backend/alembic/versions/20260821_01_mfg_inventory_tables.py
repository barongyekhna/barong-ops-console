"""M 系列 · 制造库存五张表。

物料/成品共用主档 + BOM + 单据头 + 只增流水 + 单号计数器。归属列叫
``factory_org_id``(不叫 org_id,避开 C18G 自动盖章)。

Revision ID: 20260821_01_mfg_inventory_tables
Revises: 20260813_01_users_is_bot
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_01_mfg_inventory_tables"
down_revision: str | Sequence[str] | None = "20260813_01_users_is_bot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QTY = sa.Numeric(14, 3)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "mfg_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "factory_org_id", "code", name="uq_mfg_items_factory_org_id"
        ),
        sa.CheckConstraint("kind IN ('part', 'product')", name="ck_mfg_items_kind"),
    )
    op.create_index(
        "ix_mfg_items_factory_kind", "mfg_items", ["factory_org_id", "kind"]
    )

    op.create_table(
        "mfg_bom_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("mfg_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "part_id",
            sa.Uuid(),
            sa.ForeignKey("mfg_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "product_id", "part_id", name="uq_mfg_bom_lines_product_id"
        ),
        sa.CheckConstraint(
            "mode IN ('per_unit', 'per_carton')", name="ck_mfg_bom_lines_mode"
        ),
        sa.CheckConstraint("qty > 0", name="ck_mfg_bom_lines_qty"),
    )
    op.create_index("ix_mfg_bom_lines_product_id", "mfg_bom_lines", ["product_id"])
    op.create_index("ix_mfg_bom_lines_part_id", "mfg_bom_lines", ["part_id"])

    op.create_table(
        "mfg_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column("doc_type", sa.String(16), nullable=False),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.String(64), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "factory_org_id", "doc_no", name="uq_mfg_documents_factory_org_id"
        ),
        sa.CheckConstraint(
            "doc_type IN ('receipt', 'production', 'shipment', 'adjustment')",
            name="ck_mfg_documents_doc_type",
        ),
    )
    op.create_index(
        "ix_mfg_documents_factory_created",
        "mfg_documents",
        ["factory_org_id", "created_at"],
    )

    op.create_table(
        "mfg_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("mfg_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("mfg_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("qty_delta", QTY, nullable=False),
        _created_at(),
    )
    op.create_index(
        "ix_mfg_movements_factory_item_created",
        "mfg_movements",
        ["factory_org_id", "item_id", "created_at"],
    )
    op.create_index("ix_mfg_movements_document_id", "mfg_movements", ["document_id"])

    op.create_table(
        "mfg_doc_counters",
        sa.Column("factory_org_id", sa.String(40), primary_key=True),
        sa.Column("doc_type", sa.String(16), primary_key=True),
        sa.Column("next_no", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mfg_doc_counters")
    op.drop_index("ix_mfg_movements_document_id", table_name="mfg_movements")
    op.drop_index("ix_mfg_movements_factory_item_created", table_name="mfg_movements")
    op.drop_table("mfg_movements")
    op.drop_index("ix_mfg_documents_factory_created", table_name="mfg_documents")
    op.drop_table("mfg_documents")
    op.drop_index("ix_mfg_bom_lines_part_id", table_name="mfg_bom_lines")
    op.drop_index("ix_mfg_bom_lines_product_id", table_name="mfg_bom_lines")
    op.drop_table("mfg_bom_lines")
    op.drop_index("ix_mfg_items_factory_kind", table_name="mfg_items")
    op.drop_table("mfg_items")
