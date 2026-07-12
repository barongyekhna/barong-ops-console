"""Add the durable Record-to-Asset retention deletion outbox.

Revision ID: c19_record_20260712_04
Revises: c19_record_20260712_03
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_record_20260712_04"
down_revision: str | None = "c19_record_20260712_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "record_asset_coordination",
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "asset_id", name=op.f("pk_record_asset_coordination")
        ),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "insert into record_asset_coordination (asset_id, created_at) "
            "select asset_id, CURRENT_TIMESTAMP from ("
            "select asset_id from record_asset_references union "
            "select asset_id from moment_asset_references"
            ") as existing_assets"
        )
    )
    op.create_table(
        "record_retention_operations",
        sa.Column("operation_id", sa.String(length=68), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("delete_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("approved_maximum_records", sa.Integer(), nullable=False),
        sa.Column("approved_maximum_asset_jobs", sa.Integer(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("asset_jobs_enqueued_count", sa.Integer(), nullable=False),
        sa.Column("asset_jobs_completed_count", sa.Integer(), nullable=False),
        sa.Column("next_batch_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approved_maximum_records between 1 and 100000",
            name=op.f(
                "ck_record_retention_operations_approved_maximum_supported"
            ),
        ),
        sa.CheckConstraint(
            "approved_maximum_asset_jobs between 1 and 100000",
            name=op.f(
                "ck_record_retention_operations_approved_asset_maximum_supported"
            ),
        ),
        sa.CheckConstraint(
            "asset_jobs_enqueued_count between 0 and approved_maximum_asset_jobs",
            name=op.f(
                "ck_record_retention_operations_asset_jobs_enqueued_within_maximum"
            ),
        ),
        sa.CheckConstraint(
            "asset_jobs_completed_count between 0 and asset_jobs_enqueued_count",
            name=op.f(
                "ck_record_retention_operations_asset_jobs_completed_within_enqueued"
            ),
        ),
        sa.CheckConstraint(
            "affected_count >= 0",
            name=op.f("ck_record_retention_operations_affected_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "affected_count <= approved_maximum_records",
            name=op.f(
                "ck_record_retention_operations_affected_within_approved_maximum"
            ),
        ),
        sa.CheckConstraint(
            "next_batch_ordinal >= 0",
            name=op.f(
                "ck_record_retention_operations_next_batch_ordinal_nonnegative"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "operation_id", name=op.f("pk_record_retention_operations")
        ),
    )
    op.create_index(
        "ix_record_retention_operations_completed_at",
        "record_retention_operations",
        ["completed_at"],
        unique=False,
    )
    op.create_table(
        "record_retention_batches",
        sa.Column("operation_id", sa.String(length=68), nullable=False),
        sa.Column("batch_ordinal", sa.Integer(), nullable=False),
        sa.Column("maximum_records", sa.Integer(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("cumulative_affected_count", sa.Integer(), nullable=False),
        sa.Column("operation_complete", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "batch_ordinal >= 0",
            name=op.f("ck_record_retention_batches_batch_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "maximum_records between 1 and 1000",
            name=op.f("ck_record_retention_batches_maximum_records_supported"),
        ),
        sa.CheckConstraint(
            "affected_count between 0 and maximum_records",
            name=op.f(
                "ck_record_retention_batches_affected_within_batch_maximum"
            ),
        ),
        sa.CheckConstraint(
            "cumulative_affected_count >= affected_count",
            name=op.f(
                "ck_record_retention_batches_cumulative_count_consistent"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["record_retention_operations.operation_id"],
            name=op.f(
                "fk_record_retention_batches_operation_id_record_retention_operations"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "operation_id",
            "batch_ordinal",
            name=op.f("pk_record_retention_batches"),
        ),
    )
    op.create_table(
        "record_asset_deletion_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("retention_operation_id", sa.String(length=68), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f(
                "ck_record_asset_deletion_outbox_attempt_count_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "state in ('pending','authorized','completed','protected')",
            name=op.f("ck_record_asset_deletion_outbox_state_supported"),
        ),
        sa.CheckConstraint(
            "outcome is null or outcome in ('accepted','protected')",
            name=op.f("ck_record_asset_deletion_outbox_outcome_supported"),
        ),
        sa.CheckConstraint(
            "((lease_owner is null and lease_until is null) or "
            "(lease_owner is not null and lease_until is not null))",
            name=op.f("ck_record_asset_deletion_outbox_lease_pair_consistent"),
        ),
        sa.CheckConstraint(
            "(state in ('pending','authorized') and outcome is null and completed_at is null) or "
            "(state = 'completed' and outcome = 'accepted' and "
            "completed_at is not null and lease_owner is null and lease_until is null) or "
            "(state = 'protected' and outcome = 'protected' and "
            "completed_at is not null and lease_owner is null and lease_until is null)",
            name=op.f("ck_record_asset_deletion_outbox_completion_consistent"),
        ),
        sa.CheckConstraint(
            "(state = 'pending' and authorized_at is null) or "
            "(state in ('authorized','completed') and authorized_at is not null) or "
            "state = 'protected'",
            name=op.f(
                "ck_record_asset_deletion_outbox_authorization_consistent"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_record_asset_deletion_outbox")
        ),
        sa.ForeignKeyConstraint(
            ["retention_operation_id"],
            ["record_retention_operations.operation_id"],
            name=op.f(
                "fk_record_asset_deletion_outbox_retention_operation_id_record_retention_operations"
            ),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "record_id",
            "asset_id",
            name="uq_record_asset_deletion_outbox_record_asset",
        ),
    )
    op.create_index(
        "ix_record_asset_deletion_outbox_state_created",
        "record_asset_deletion_outbox",
        ["state", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_record_asset_deletion_outbox_retention_operation",
        "record_asset_deletion_outbox",
        ["retention_operation_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_record_asset_deletion_outbox_asset_state",
        "record_asset_deletion_outbox",
        ["asset_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_record_asset_deletion_outbox_authorized_at",
        "record_asset_deletion_outbox",
        ["authorized_at"],
        unique=False,
    )
    op.create_index(
        "ix_record_asset_deletion_outbox_lease_until",
        "record_asset_deletion_outbox",
        ["lease_until"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    outbox_count = int(
        connection.execute(sa.text("select count(*) from record_asset_deletion_outbox"))
        .scalar_one()
    )
    operation_count = int(
        connection.execute(sa.text("select count(*) from record_retention_operations"))
        .scalar_one()
    )
    if outbox_count or operation_count:
        raise RuntimeError(
            "Refusing to downgrade C19 Record v4 while durable retention state "
            "exists; drain or explicitly archive it first"
        )
    op.drop_index(
        "ix_record_asset_deletion_outbox_authorized_at",
        table_name="record_asset_deletion_outbox",
    )
    op.drop_index(
        "ix_record_asset_deletion_outbox_retention_operation",
        table_name="record_asset_deletion_outbox",
    )
    op.drop_index(
        "ix_record_asset_deletion_outbox_lease_until",
        table_name="record_asset_deletion_outbox",
    )
    op.drop_index(
        "ix_record_asset_deletion_outbox_asset_state",
        table_name="record_asset_deletion_outbox",
    )
    op.drop_index(
        "ix_record_asset_deletion_outbox_state_created",
        table_name="record_asset_deletion_outbox",
    )
    op.drop_table("record_asset_deletion_outbox")
    op.drop_table("record_retention_batches")
    op.drop_index(
        "ix_record_retention_operations_completed_at",
        table_name="record_retention_operations",
    )
    op.drop_table("record_retention_operations")
    op.drop_table("record_asset_coordination")
