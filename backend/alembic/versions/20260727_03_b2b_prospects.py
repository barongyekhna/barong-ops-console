"""B2B prospecting tables.

Revision ID: 20260727_03_b2b_prospects
Revises: 20260727_02_b2b_permissions
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_03_b2b_prospects"
down_revision: str | Sequence[str] | None = "20260727_02_b2b_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_prospect_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_type", sa.String(length=64), nullable=False),
        sa.Column("store_type_label", sa.String(length=128), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("query_template", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_type", "country", "query_template",
                            name="uq_b2b_prospect_queries_combo"),
        sa.CheckConstraint("country IN ('US', 'CA', 'MX')",
                           name="ck_b2b_prospect_queries_country"),
    )
    op.create_index("ix_b2b_prospect_queries_active", "b2b_prospect_queries",
                    ["active"])

    op.create_table(
        "b2b_target_cities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=False),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country", "region", "city",
                            name="uq_b2b_target_cities_place"),
        sa.CheckConstraint("country IN ('US', 'CA', 'MX')",
                           name="ck_b2b_target_cities_country"),
    )
    op.create_index("ix_b2b_target_cities_country_active", "b2b_target_cities",
                    ["country", "active"])

    op.create_table(
        "b2b_prospect_sweeps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", "city_id", name="uq_b2b_prospect_sweeps_pair"),
    )
    op.create_index("ix_b2b_prospect_sweeps_ran_at", "b2b_prospect_sweeps", ["ran_at"])

    op.create_table(
        "b2b_prospects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("store_name", sa.String(length=255), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=True),
        sa.Column("reviews_count", sa.Integer(), nullable=True),
        sa.Column("store_type", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("source_query", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("email_source", sa.String(length=64), nullable=True),
        sa.Column("contact_name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="new"),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_b2b_prospects_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('new', 'approved', 'rejected', 'contacted', "
            "'replied', 'customer')",
            name="ck_b2b_prospects_status",
        ),
    )
    op.create_index("ix_b2b_prospects_status", "b2b_prospects", ["status"])
    op.create_index("ix_b2b_prospects_country_store_type", "b2b_prospects",
                    ["country", "store_type"])


def downgrade() -> None:
    op.drop_index("ix_b2b_prospects_country_store_type", table_name="b2b_prospects")
    op.drop_index("ix_b2b_prospects_status", table_name="b2b_prospects")
    op.drop_table("b2b_prospects")
    op.drop_index("ix_b2b_prospect_sweeps_ran_at", table_name="b2b_prospect_sweeps")
    op.drop_table("b2b_prospect_sweeps")
    op.drop_index("ix_b2b_target_cities_country_active", table_name="b2b_target_cities")
    op.drop_table("b2b_target_cities")
    op.drop_index("ix_b2b_prospect_queries_active", table_name="b2b_prospect_queries")
    op.drop_table("b2b_prospect_queries")
