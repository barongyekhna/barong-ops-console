"""RD 系列 · 控制台内置远程桌面:设备登记、公用机名单、操控台账、握手信封。

四张表分四件事:

- ``rd_devices``           谁的哪台机器,在不在线,是不是公用机
  (device_uuid 由被控端客户端自持,与 VPN 的设备身份互不依赖)
- ``rd_unattended_grants`` 公用机放谁免同意进
- ``rd_sessions``          每一次操控的完整台账(只增不删)
- ``rd_signals``           WebRTC 握手期间两边互递的信封(建连完就清)

**四张表都刻意不带 ``org_id``。** 这个模块不属于任何组织、所有登录用户都能用,而带
``org_id`` 的表会被 C18G 数据隔离按当前组织盖一层,那正好是这里不要的。归属只认
``owner_user_id``——人,不是公司。

同理本迁移**不含权限码**:门不在控制台这一层,在被控机本地那个原生同意框。加权限
码反而会把「全员可用」这件事变成假的。

Revision ID: 20260911_03_rd_remote_desktop
Revises: 20260911_02_mfg_cost_permissions
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_03_rd_remote_desktop"
down_revision: str | Sequence[str] | None = "20260911_02_mfg_cost_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rd_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_uuid", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("agent_version", sa.String(length=32), nullable=False),
        sa.Column(
            "is_unattended",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("unattended_marked_by", sa.BigInteger(), nullable=True),
        sa.Column("unattended_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["unattended_marked_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_uuid", name="uq_rd_devices_device_uuid"),
    )
    op.create_index("ix_rd_devices_owner", "rd_devices", ["owner_user_id"])
    op.create_index("ix_rd_devices_last_seen", "rd_devices", ["last_seen_at"])

    op.create_table(
        "rd_unattended_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.BigInteger(), nullable=False),
        sa.Column("granted_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["rd_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grantee_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id", "grantee_user_id", name="uq_rd_unattended_grants_pair"
        ),
    )
    op.create_index(
        "ix_rd_unattended_grants_grantee", "rd_unattended_grants", ["grantee_user_id"]
    )

    op.create_table(
        "rd_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("controller_user_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("consent_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "state IN ('requested', 'consented', 'active', 'denied', 'expired', 'ended')",
            name="ck_rd_sessions_state",
        ),
        sa.CheckConstraint(
            "consent_mode IN ('prompt', 'unattended')",
            name="ck_rd_sessions_consent_mode",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["rd_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["controller_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rd_sessions_device_state", "rd_sessions", ["device_id", "state"]
    )
    op.create_index("ix_rd_sessions_controller", "rd_sessions", ["controller_user_id"])
    op.create_index("ix_rd_sessions_requested_at", "rd_sessions", ["requested_at"])

    op.create_table(
        "rd_signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sender IN ('controller', 'agent')", name="ck_rd_signals_sender"
        ),
        sa.CheckConstraint(
            "kind IN ('offer', 'answer', 'ice')", name="ck_rd_signals_kind"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["rd_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rd_signals_session_id", "rd_signals", ["session_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_rd_signals_session_id", table_name="rd_signals")
    op.drop_table("rd_signals")
    op.drop_index("ix_rd_sessions_requested_at", table_name="rd_sessions")
    op.drop_index("ix_rd_sessions_controller", table_name="rd_sessions")
    op.drop_index("ix_rd_sessions_device_state", table_name="rd_sessions")
    op.drop_table("rd_sessions")
    op.drop_index(
        "ix_rd_unattended_grants_grantee", table_name="rd_unattended_grants"
    )
    op.drop_table("rd_unattended_grants")
    op.drop_index("ix_rd_devices_last_seen", table_name="rd_devices")
    op.drop_index("ix_rd_devices_owner", table_name="rd_devices")
    op.drop_table("rd_devices")
