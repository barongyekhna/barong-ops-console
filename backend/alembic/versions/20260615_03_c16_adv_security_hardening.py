"""add C16 advanced security hardening tables

Revision ID: c16_adv_security_001
Revises: c16_fix4_login_lockout_001
Create Date: 2026-06-15

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c16_adv_security_001"
down_revision: str | Sequence[str] | None = "c16_fix4_login_lockout_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_rate_limit_buckets",
        sa.Column("bucket_key_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("endpoint_key", sa.String(length=128), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_rate_limit_buckets")),
        sa.UniqueConstraint(
            "bucket_key_hash",
            name=op.f("uq_security_rate_limit_buckets_bucket_key_hash"),
        ),
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_blocked_until"),
        "security_rate_limit_buckets",
        ["blocked_until"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_endpoint_key"),
        "security_rate_limit_buckets",
        ["endpoint_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_expires_at"),
        "security_rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_identifier_hash"),
        "security_rate_limit_buckets",
        ["identifier_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_scope"),
        "security_rate_limit_buckets",
        ["scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_rate_limit_buckets_window_started_at"),
        "security_rate_limit_buckets",
        ["window_started_at"],
        unique=False,
    )

    op.create_table(
        "security_replay_nonces",
        sa.Column("global_dedup_key_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("nonce_key_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_replay_nonces")),
        sa.UniqueConstraint(
            "global_dedup_key_hash",
            name=op.f("uq_security_replay_nonces_global_dedup_key_hash"),
        ),
    )
    op.create_index(
        op.f("ix_security_replay_nonces_expires_at"),
        "security_replay_nonces",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_replay_nonces_first_seen_at"),
        "security_replay_nonces",
        ["first_seen_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_replay_nonces_nonce_key_hash"),
        "security_replay_nonces",
        ["nonce_key_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_security_replay_nonces_scope"),
        "security_replay_nonces",
        ["scope"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_security_replay_nonces_scope"),
        table_name="security_replay_nonces",
    )
    op.drop_index(
        op.f("ix_security_replay_nonces_nonce_key_hash"),
        table_name="security_replay_nonces",
    )
    op.drop_index(
        op.f("ix_security_replay_nonces_first_seen_at"),
        table_name="security_replay_nonces",
    )
    op.drop_index(
        op.f("ix_security_replay_nonces_expires_at"),
        table_name="security_replay_nonces",
    )
    op.drop_table("security_replay_nonces")

    op.drop_index(
        op.f("ix_security_rate_limit_buckets_window_started_at"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_security_rate_limit_buckets_scope"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_security_rate_limit_buckets_identifier_hash"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_security_rate_limit_buckets_expires_at"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_security_rate_limit_buckets_endpoint_key"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_index(
        op.f("ix_security_rate_limit_buckets_blocked_until"),
        table_name="security_rate_limit_buckets",
    )
    op.drop_table("security_rate_limit_buckets")
