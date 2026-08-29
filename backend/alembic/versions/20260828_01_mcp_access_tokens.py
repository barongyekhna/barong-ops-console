"""MCP personal access tokens: one per human account, hash-only.

External desktop agents (Codex etc.) present ``Authorization: Bearer <token>``
to the console's MCP sidecars; the sidecar looks the sha256 hash up here and
acts as that user. Replaces the single shared K_MCP_BEARER_TOKEN. Purely
additive — safe to roll forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260828_01_mcp_access_tokens"
down_revision = "20260823_01_user_profile_settings"
branch_labels = None
depends_on = None


def _user_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _table_exists("mcp_access_tokens"):
        return
    op.create_table(
        "mcp_access_tokens",
        sa.Column("id", _user_id_type(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            _user_id_type(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("issued_by_user_id", _user_id_type(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(45), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_user_id", _user_id_type(), nullable=True),
        sa.Column("metadata", _json_type(), nullable=False, server_default="{}"),
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
        sa.UniqueConstraint("user_id", name="uq_mcp_access_tokens_user_id"),
        sa.UniqueConstraint("token_hash", name="uq_mcp_access_tokens_token_hash"),
    )


def downgrade() -> None:
    if _table_exists("mcp_access_tokens"):
        op.drop_table("mcp_access_tokens")
