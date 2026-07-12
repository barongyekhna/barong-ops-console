"""Make C19 membership native to active users, independent of affiliations.

Revision ID: 20260712_01_c19_native_access
Revises: 20260711_03_render_staging
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_01_c19_native_access"
down_revision: str | Sequence[str] | None = "20260711_03_render_staging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MEMBERS = "c19_conversation_members"
# Supply the semantic name; Base.metadata's naming convention renders the
# physical PostgreSQL name as
# ck_c19_conversation_members_affiliation_snapshot_consistent.  Passing that
# already-prefixed name here would apply the convention twice.
SNAPSHOT_CHECK = "affiliation_snapshot_consistent"
PROFILE_FK = "fk_c19_conversation_members_user_profile"


def upgrade() -> None:
    # Repair the global one-card-per-user invariant before membership rows gain
    # an affiliation-independent profile reference.
    op.execute(
        sa.text(
            """
            INSERT INTO c19_profiles (
                user_id,
                display_name,
                created_at,
                updated_at
            )
            SELECT
                users.id,
                CASE
                    WHEN length(trim(users.username)) > 0
                    THEN trim(users.username)
                    ELSE 'User ' || CAST(users.id AS VARCHAR)
                END,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM users
            WHERE NOT EXISTS (
                SELECT 1
                FROM c19_profiles
                WHERE c19_profiles.user_id = users.id
            )
            """
        )
    )

    with op.batch_alter_table(MEMBERS) as batch_op:
        batch_op.alter_column(
            "affiliation_id",
            existing_type=sa.String(length=64),
            nullable=True,
        )
        batch_op.alter_column(
            "org_id_at_join",
            existing_type=sa.String(length=40),
            nullable=True,
        )
        batch_op.create_check_constraint(
            SNAPSHOT_CHECK,
            "(affiliation_id IS NULL AND org_id_at_join IS NULL) OR "
            "(affiliation_id IS NOT NULL AND org_id_at_join IS NOT NULL)",
        )
        batch_op.create_foreign_key(
            PROFILE_FK,
            "c19_profiles",
            ["user_id"],
            ["user_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    null_snapshot_count = int(
        bind.execute(
            sa.text(
                """
                SELECT count(*)
                FROM c19_conversation_members
                WHERE affiliation_id IS NULL OR org_id_at_join IS NULL
                """
            )
        ).scalar_one()
    )
    if null_snapshot_count:
        raise RuntimeError(
            "Cannot downgrade C19 native-user access while affiliation-free "
            "conversation members exist."
        )

    with op.batch_alter_table(MEMBERS) as batch_op:
        batch_op.drop_constraint(PROFILE_FK, type_="foreignkey")
        batch_op.drop_constraint(SNAPSHOT_CHECK, type_="check")
        batch_op.alter_column(
            "org_id_at_join",
            existing_type=sa.String(length=40),
            nullable=False,
        )
        batch_op.alter_column(
            "affiliation_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
