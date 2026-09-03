"""User self-service profile settings: nickname, theme_pref, avatar blob.

Adds two nullable columns to c19_profiles (nickname, theme_pref) and a small
user_avatars table holding the avatar image bytes (DB is source of truth; the
serve endpoint streams them). Purely additive — safe to roll forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260823_01_user_profile_settings"
down_revision = "20260822_01_backfill_orgscoped_org_id"
branch_labels = None
depends_on = None


def _user_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def upgrade() -> None:
    if not _column_exists("c19_profiles", "nickname"):
        op.add_column(
            "c19_profiles", sa.Column("nickname", sa.String(255), nullable=True)
        )
    if not _column_exists("c19_profiles", "theme_pref"):
        op.add_column(
            "c19_profiles", sa.Column("theme_pref", sa.String(16), nullable=True)
        )
    if not _table_exists("user_avatars"):
        op.create_table(
            "user_avatars",
            sa.Column(
                "user_id",
                _user_id_type(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
            sa.Column("mime_type", sa.String(64), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
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


def downgrade() -> None:
    if _table_exists("user_avatars"):
        op.drop_table("user_avatars")
    if _column_exists("c19_profiles", "theme_pref"):
        op.drop_column("c19_profiles", "theme_pref")
    if _column_exists("c19_profiles", "nickname"):
        op.drop_column("c19_profiles", "nickname")
