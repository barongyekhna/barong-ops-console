"""M 系列 · 出货成本明细:批次价上流水 + 工序库 + 价格事件 + 成本表快照。

价格不是属性,是事件。物料主档上永远没有"单价"字段,就像它上面永远没有"库存数"
字段一样——铜价涨了不是去改一个格子,而是下一批入库时多出一条流水,老批次一个字
不动。所以:

- ``mfg_movements`` 加 ``unit_price`` / ``unit_freight``:**一条正向入库流水就是一个
  批次**,价格跟着流水走,天然获得"只增不改"的保护。价格另开一张表就要把数量再存
  一遍,同一个数字存两份迟早不一致。
- ``mfg_items`` 加 ``is_volatile``:波动料(电线受铜价影响这类)勾上以后,含它的成本
  表有效期从 30 天缩到 7 天。
- 三张事件表(参考价 / 工价 / 出厂价)共用同一条规矩:改价 = 新增一行。
- 三张快照表:成本表定稿之后再也不变,发出去的数字收不回来。

本迁移**不含权限码**,权限在 20260911_02 里单独同步(permission registry 只在表全空
时才从 seed 自动播种,所以每个模块得自己写迁移——B2B/CS/F/W 四次栽在这)。

Revision ID: 20260911_01_mfg_cost_tables
Revises: 20260910_01_mfg_code_groups
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_01_mfg_cost_tables"
down_revision: str | Sequence[str] | None = "20260910_01_mfg_code_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QTY = sa.Numeric(14, 3)
MONEY = sa.Numeric(14, 4)


def upgrade() -> None:
    # ---------------------------------------------------------- 既有两张表加列
    op.add_column(
        "mfg_movements", sa.Column("unit_price", MONEY, nullable=True)
    )
    op.add_column(
        "mfg_movements", sa.Column("unit_freight", MONEY, nullable=True)
    )
    op.add_column(
        "mfg_movements",
        sa.Column(
            "price_is_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "mfg_items",
        sa.Column(
            "is_volatile", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    # ---------------------------------------------------------- 工序库 + 工价
    op.create_table(
        "mfg_labor_processes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
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
            "factory_org_id", "name", name="uq_mfg_labor_processes_factory_org_id"
        ),
    )
    op.create_index(
        "ix_mfg_labor_processes_factory", "mfg_labor_processes", ["factory_org_id"]
    )

    op.create_table(
        "mfg_labor_rates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "process_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_labor_processes.id",
                ondelete="CASCADE",
                name="fk_mfg_labor_rates_process_id_mfg_labor_processes",
            ),
            nullable=False,
        ),
        sa.Column("rate", MONEY, nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("rate >= 0", name="ck_mfg_labor_rates_rate"),
    )
    op.create_index(
        "ix_mfg_labor_rates_process_effective",
        "mfg_labor_rates",
        ["process_id", "effective_date"],
    )

    op.create_table(
        "mfg_labor_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_items.id",
                ondelete="CASCADE",
                name="fk_mfg_labor_lines_product_id_mfg_items",
            ),
            nullable=False,
        ),
        sa.Column(
            "process_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_labor_processes.id",
                ondelete="RESTRICT",
                name="fk_mfg_labor_lines_process_id_mfg_labor_processes",
            ),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "product_id", "process_id", name="uq_mfg_labor_lines_product_id"
        ),
        sa.CheckConstraint(
            "mode IN ('per_unit', 'per_batch')", name="ck_mfg_labor_lines_mode"
        ),
        sa.CheckConstraint("qty > 0", name="ck_mfg_labor_lines_qty"),
    )
    op.create_index(
        "ix_mfg_labor_lines_product_id", "mfg_labor_lines", ["product_id"]
    )

    # ---------------------------------------------------------- 参考价 / 出厂价
    op.create_table(
        "mfg_item_prices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_items.id",
                ondelete="CASCADE",
                name="fk_mfg_item_prices_item_id_mfg_items",
            ),
            nullable=False,
        ),
        sa.Column("unit_price", MONEY, nullable=False),
        sa.Column("freight_per_unit", MONEY, nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source IN ('quote', 'manual')", name="ck_mfg_item_prices_source"
        ),
        sa.CheckConstraint("unit_price >= 0", name="ck_mfg_item_prices_unit_price"),
    )
    op.create_index(
        "ix_mfg_item_prices_item_effective",
        "mfg_item_prices",
        ["item_id", "effective_date"],
    )

    op.create_table(
        "mfg_sale_prices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_items.id",
                ondelete="CASCADE",
                name="fk_mfg_sale_prices_product_id_mfg_items",
            ),
            nullable=False,
        ),
        sa.Column("unit_price", MONEY, nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("unit_price >= 0", name="ck_mfg_sale_prices_unit_price"),
    )
    op.create_index(
        "ix_mfg_sale_prices_product_effective",
        "mfg_sale_prices",
        ["product_id", "effective_date"],
    )

    # ---------------------------------------------------------- 成本表快照
    op.create_table(
        "mfg_cost_sheets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column("sheet_no", sa.String(32), nullable=False),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_items.id",
                ondelete="RESTRICT",
                name="fk_mfg_cost_sheets_product_id_mfg_items",
            ),
            nullable=False,
        ),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("product_unit", sa.String(20), nullable=False),
        sa.Column("batch_qty", QTY, nullable=False),
        sa.Column("basis", sa.String(16), nullable=False),
        sa.Column(
            "source_document_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_documents.id",
                ondelete="SET NULL",
                name="fk_mfg_cost_sheets_source_document_id_mfg_documents",
            ),
            nullable=True,
        ),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column(
            "has_volatile", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "missing_price_count", sa.Integer(), nullable=False, server_default="0"
        ),
        # 缺价时这四个全是 NULL,不是 0:给一个看着完整的假总价比不给危险得多
        sa.Column("material_total", MONEY, nullable=True),
        sa.Column("freight_total", MONEY, nullable=True),
        sa.Column("labor_total", MONEY, nullable=True),
        sa.Column("unit_cost", MONEY, nullable=True),
        sa.Column("sale_price", MONEY, nullable=True),
        sa.Column("actor_user_id", sa.String(64), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "factory_org_id", "sheet_no", name="uq_mfg_cost_sheets_factory_org_id"
        ),
        sa.CheckConstraint(
            "basis IN ('actual', 'estimate')", name="ck_mfg_cost_sheets_basis"
        ),
        sa.CheckConstraint("batch_qty > 0", name="ck_mfg_cost_sheets_batch_qty"),
    )
    op.create_index(
        "ix_mfg_cost_sheets_factory_created",
        "mfg_cost_sheets",
        ["factory_org_id", "created_at"],
    )
    op.create_index(
        "ix_mfg_cost_sheets_product_id", "mfg_cost_sheets", ["product_id"]
    )

    op.create_table(
        "mfg_cost_sheet_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "sheet_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_cost_sheets.id",
                ondelete="CASCADE",
                name="fk_mfg_cost_sheet_lines_sheet_id_mfg_cost_sheets",
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("qty", QTY, nullable=False),
        sa.Column("unit_price", MONEY, nullable=True),
        sa.Column("unit_freight", MONEY, nullable=True),
        sa.Column("line_total", MONEY, nullable=True),
        sa.Column(
            "is_missing_price",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("batch_breakdown", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('material', 'labor')", name="ck_mfg_cost_sheet_lines_kind"
        ),
    )
    op.create_index(
        "ix_mfg_cost_sheet_lines_sheet_id", "mfg_cost_sheet_lines", ["sheet_id"]
    )

    op.create_table(
        "mfg_cost_sheet_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("factory_org_id", sa.String(40), nullable=False),
        sa.Column(
            "sheet_id",
            sa.Uuid(),
            sa.ForeignKey(
                "mfg_cost_sheets.id",
                ondelete="CASCADE",
                name="fk_mfg_cost_sheet_shares_sheet_id_mfg_cost_sheets",
            ),
            nullable=False,
        ),
        sa.Column("share_mode", sa.String(16), nullable=False),
        sa.Column("card_token", sa.String(8), nullable=False),
        sa.Column("recipient_user_id", sa.String(64), nullable=False),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("conversation_id", sa.String(128), nullable=False),
        sa.Column("message_id", sa.String(64), nullable=False),
        # 回读确认那条消息真的存在的时刻;为空 = 发过但没验证上,不算数
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.String(64), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "share_mode IN ('full', 'price_only')",
            name="ck_mfg_cost_sheet_shares_share_mode",
        ),
    )
    op.create_index(
        "ix_mfg_cost_sheet_shares_sheet_id", "mfg_cost_sheet_shares", ["sheet_id"]
    )
    op.create_index(
        "ix_mfg_cost_sheet_shares_factory_created",
        "mfg_cost_sheet_shares",
        ["factory_org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mfg_cost_sheet_shares_factory_created",
        table_name="mfg_cost_sheet_shares",
    )
    op.drop_index(
        "ix_mfg_cost_sheet_shares_sheet_id", table_name="mfg_cost_sheet_shares"
    )
    op.drop_table("mfg_cost_sheet_shares")

    op.drop_index(
        "ix_mfg_cost_sheet_lines_sheet_id", table_name="mfg_cost_sheet_lines"
    )
    op.drop_table("mfg_cost_sheet_lines")

    op.drop_index("ix_mfg_cost_sheets_product_id", table_name="mfg_cost_sheets")
    op.drop_index("ix_mfg_cost_sheets_factory_created", table_name="mfg_cost_sheets")
    op.drop_table("mfg_cost_sheets")

    op.drop_index(
        "ix_mfg_sale_prices_product_effective", table_name="mfg_sale_prices"
    )
    op.drop_table("mfg_sale_prices")

    op.drop_index("ix_mfg_item_prices_item_effective", table_name="mfg_item_prices")
    op.drop_table("mfg_item_prices")

    op.drop_index("ix_mfg_labor_lines_product_id", table_name="mfg_labor_lines")
    op.drop_table("mfg_labor_lines")

    op.drop_index(
        "ix_mfg_labor_rates_process_effective", table_name="mfg_labor_rates"
    )
    op.drop_table("mfg_labor_rates")

    op.drop_index(
        "ix_mfg_labor_processes_factory", table_name="mfg_labor_processes"
    )
    op.drop_table("mfg_labor_processes")

    op.drop_column("mfg_items", "is_volatile")
    op.drop_column("mfg_movements", "price_is_estimated")
    op.drop_column("mfg_movements", "unit_freight")
    op.drop_column("mfg_movements", "unit_price")
