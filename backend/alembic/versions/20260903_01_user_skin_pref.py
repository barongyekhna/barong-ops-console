"""User self-service profile settings: skin_pref (color theme choice).

Adds one nullable column to c19_profiles. Sibling to theme_pref
(20260823_01_user_profile_settings) — theme_pref picks light/dark,
skin_pref picks which of the three color palettes. Purely additive —
safe to roll forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260903_01_user_skin_pref"
down_revision = "20260902_02_index_storage_events_record_id"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _column_exists("c19_profiles", "skin_pref"):
        op.add_column(
            "c19_profiles", sa.Column("skin_pref", sa.String(16), nullable=True)
        )


def downgrade() -> None:
    if _column_exists("c19_profiles", "skin_pref"):
        op.drop_column("c19_profiles", "skin_pref")
