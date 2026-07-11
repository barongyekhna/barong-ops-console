"""C19 durable control-metadata core

The Barong database owns communication identity, multi-organization affiliation,
relationship, block, conversation, participant, and user-setting metadata only.
Message records, read/delivery positions, attachment metadata/bytes, and Moments
remain outside this migration.

Revision ID: 20260711_01_c19_control_core
Revises: 20260710_05_k_brand_guard
Create Date: 2026-07-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_01_c19_control_core"
down_revision: str | Sequence[str] | None = "20260710_05_k_brand_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_id_type() -> sa.BigInteger:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _create_profiles() -> None:
    op.create_table(
        "c19_profiles",
        sa.Column("user_id", _user_id_type(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("avatar_ref", sa.String(length=512), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name=op.f("ck_c19_profiles_display_name_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_c19_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_c19_profiles")),
    )
    op.create_index(
        "ix_c19_profiles_display_name",
        "c19_profiles",
        ["display_name"],
        unique=False,
    )
    op.create_index(
        "ix_c19_profiles_updated_at",
        "c19_profiles",
        ["updated_at"],
        unique=False,
    )


def _create_affiliations() -> None:
    op.create_table(
        "c19_affiliations",
        sa.Column("affiliation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", _user_id_type(), nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("source_membership_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name=op.f("ck_c19_affiliations_role_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')",
            name=op.f("ck_c19_affiliations_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            name=op.f("fk_c19_affiliations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_membership_id"],
            ["org_memberships.membership_id"],
            name=op.f(
                "fk_c19_affiliations_source_membership_id_org_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["c19_profiles.user_id"],
            name=op.f("fk_c19_affiliations_user_id_c19_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "affiliation_id",
            name=op.f("pk_c19_affiliations"),
        ),
        sa.UniqueConstraint(
            "affiliation_id",
            "user_id",
            "org_id",
            name="uq_c19_affiliations_identity_scope",
        ),
        sa.UniqueConstraint(
            "source_membership_id",
            name="uq_c19_affiliations_source_membership_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "org_id",
            name="uq_c19_affiliations_user_id_org_id",
        ),
    )
    op.create_index(
        "ix_c19_affiliations_org_id_status",
        "c19_affiliations",
        ["org_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_affiliations_updated_at",
        "c19_affiliations",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_c19_affiliations_user_id_status",
        "c19_affiliations",
        ["user_id", "status"],
        unique=False,
    )


def _create_friend_requests() -> None:
    op.create_table(
        "c19_friend_requests",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("pair_key", sa.String(length=128), nullable=False),
        sa.Column("requester_user_id", _user_id_type(), nullable=False),
        sa.Column("addressee_user_id", _user_id_type(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("request_message", sa.String(length=500), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "requester_user_id <> addressee_user_id",
            name=op.f("ck_c19_friend_requests_participants_distinct"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
            name=op.f("ck_c19_friend_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(pair_key)) > 0",
            name=op.f("ck_c19_friend_requests_pair_key_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["addressee_user_id"],
            ["c19_profiles.user_id"],
            name=op.f(
                "fk_c19_friend_requests_addressee_user_id_c19_profiles"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["c19_profiles.user_id"],
            name=op.f(
                "fk_c19_friend_requests_requester_user_id_c19_profiles"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_id", name=op.f("pk_c19_friend_requests")),
        sa.UniqueConstraint(
            "pair_key",
            name="uq_c19_friend_requests_pair_key",
        ),
    )
    op.create_index(
        "ix_c19_friend_requests_addressee_status",
        "c19_friend_requests",
        ["addressee_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_friend_requests_requester_status",
        "c19_friend_requests",
        ["requester_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_friend_requests_status_created_at",
        "c19_friend_requests",
        ["status", "created_at"],
        unique=False,
    )


def _create_relationships() -> None:
    op.create_table(
        "c19_relationships",
        sa.Column("relationship_id", sa.String(length=64), nullable=False),
        sa.Column("pair_key", sa.String(length=128), nullable=False),
        sa.Column("user_low_id", _user_id_type(), nullable=False),
        sa.Column("user_high_id", _user_id_type(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="friends",
            nullable=False,
        ),
        sa.Column("origin_request_id", sa.String(length=64), nullable=True),
        sa.Column("established_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "user_low_id < user_high_id",
            name=op.f("ck_c19_relationships_canonical_participant_order"),
        ),
        sa.CheckConstraint(
            "status IN ('friends', 'removed')",
            name=op.f("ck_c19_relationships_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["origin_request_id"],
            ["c19_friend_requests.request_id"],
            name=op.f(
                "fk_c19_relationships_origin_request_id_c19_friend_requests"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_high_id"],
            ["c19_profiles.user_id"],
            name=op.f("fk_c19_relationships_user_high_id_c19_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_low_id"],
            ["c19_profiles.user_id"],
            name=op.f("fk_c19_relationships_user_low_id_c19_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "relationship_id",
            name=op.f("pk_c19_relationships"),
        ),
        sa.UniqueConstraint(
            "pair_key",
            name="uq_c19_relationships_pair_key",
        ),
        sa.UniqueConstraint(
            "user_low_id",
            "user_high_id",
            name="uq_c19_relationships_canonical_pair",
        ),
    )
    op.create_index(
        "ix_c19_relationships_updated_at",
        "c19_relationships",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_c19_relationships_user_high_status",
        "c19_relationships",
        ["user_high_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_relationships_user_low_status",
        "c19_relationships",
        ["user_low_id", "status"],
        unique=False,
    )


def _create_user_blocks() -> None:
    op.create_table(
        "c19_user_blocks",
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("blocker_user_id", _user_id_type(), nullable=False),
        sa.Column("blocked_user_id", _user_id_type(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "blocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "blocker_user_id <> blocked_user_id",
            name=op.f("ck_c19_user_blocks_participants_distinct"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name=op.f("ck_c19_user_blocks_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'active' AND is_active = true AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND is_active = false "
            "AND revoked_at IS NOT NULL)",
            name=op.f("ck_c19_user_blocks_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"],
            ["c19_profiles.user_id"],
            name=op.f("fk_c19_user_blocks_blocked_user_id_c19_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocker_user_id"],
            ["c19_profiles.user_id"],
            name=op.f("fk_c19_user_blocks_blocker_user_id_c19_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("block_id", name=op.f("pk_c19_user_blocks")),
        sa.UniqueConstraint(
            "blocker_user_id",
            "blocked_user_id",
            name="uq_c19_user_blocks_blocker_blocked",
        ),
    )
    op.create_index(
        "ix_c19_user_blocks_blocked_status",
        "c19_user_blocks",
        ["blocked_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_user_blocks_blocker_status",
        "c19_user_blocks",
        ["blocker_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_user_blocks_updated_at",
        "c19_user_blocks",
        ["updated_at"],
        unique=False,
    )


def _create_conversations() -> None:
    op.create_table(
        "c19_conversations",
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("direct_pair_key", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", _user_id_type(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "type IN ('direct', 'group')",
            name=op.f("ck_c19_conversations_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'closed')",
            name=op.f("ck_c19_conversations_status_valid"),
        ),
        sa.CheckConstraint(
            "(type = 'direct' AND direct_pair_key IS NOT NULL) "
            "OR (type = 'group' AND direct_pair_key IS NULL)",
            name=op.f("ck_c19_conversations_direct_pair_key_matches_type"),
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(trim(title)) > 0",
            name=op.f("ck_c19_conversations_title_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["c19_profiles.user_id"],
            name=op.f(
                "fk_c19_conversations_created_by_user_id_c19_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            name=op.f("pk_c19_conversations"),
        ),
        sa.UniqueConstraint(
            "direct_pair_key",
            name="uq_c19_conversations_direct_pair_key",
        ),
    )
    op.create_index(
        "ix_c19_conversations_type_status",
        "c19_conversations",
        ["type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_conversations_updated_at",
        "c19_conversations",
        ["updated_at"],
        unique=False,
    )


def _create_conversation_members() -> None:
    op.create_table(
        "c19_conversation_members",
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("affiliation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", _user_id_type(), nullable=False),
        sa.Column("org_id_at_join", sa.String(length=40), nullable=False),
        sa.Column(
            "role",
            sa.String(length=20),
            server_default="member",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name=op.f("ck_c19_conversation_members_role_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'left', 'removed', 'banned')",
            name=op.f("ck_c19_conversation_members_status_valid"),
        ),
        sa.CheckConstraint(
            "(status IN ('invited', 'active') AND left_at IS NULL) "
            "OR (status IN ('left', 'removed', 'banned') "
            "AND left_at IS NOT NULL)",
            name=op.f(
                "ck_c19_conversation_members_departure_state_consistent"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["affiliation_id", "user_id", "org_id_at_join"],
            [
                "c19_affiliations.affiliation_id",
                "c19_affiliations.user_id",
                "c19_affiliations.org_id",
            ],
            name="fk_c19_conversation_members_affiliation_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["c19_conversations.conversation_id"],
            name=op.f(
                "fk_c19_conversation_members_conversation_id_c19_conversations"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "member_id",
            name=op.f("pk_c19_conversation_members"),
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "user_id",
            name="uq_c19_conversation_members_conversation_user",
        ),
    )
    op.create_index(
        "ix_c19_conversation_members_conversation_status",
        "c19_conversation_members",
        ["conversation_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_conversation_members_org_status",
        "c19_conversation_members",
        ["org_id_at_join", "status"],
        unique=False,
    )
    op.create_index(
        "ix_c19_conversation_members_user_status",
        "c19_conversation_members",
        ["user_id", "status"],
        unique=False,
    )


def _create_conversation_user_settings() -> None:
    op.create_table(
        "c19_conversation_user_settings",
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", _user_id_type(), nullable=False),
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "is_muted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "notification_level",
            sa.String(length=20),
            server_default="all",
            nullable=False,
        ),
        _created_at_column(),
        _updated_at_column(),
        sa.CheckConstraint(
            "notification_level IN ('all', 'mentions', 'none')",
            name=op.f(
                "ck_c19_conversation_user_settings_notification_level_valid"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            [
                "c19_conversation_members.conversation_id",
                "c19_conversation_members.user_id",
            ],
            name="fk_c19_conversation_user_settings_member",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            "user_id",
            name=op.f("pk_c19_conversation_user_settings"),
        ),
    )
    op.create_index(
        "ix_c19_conversation_user_settings_updated_at",
        "c19_conversation_user_settings",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_c19_conversation_user_settings_user_archived",
        "c19_conversation_user_settings",
        ["user_id", "is_archived"],
        unique=False,
    )
    op.create_index(
        "ix_c19_conversation_user_settings_user_pinned",
        "c19_conversation_user_settings",
        ["user_id", "is_pinned"],
        unique=False,
    )


def _backfill_profiles_and_affiliations() -> None:
    """Backfill only authoritative facts; never infer title or primary org."""

    bind = op.get_bind()
    now = datetime.now(UTC)

    users = sa.table(
        "users",
        sa.column("id", _user_id_type()),
        sa.column("username", sa.String(length=255)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    profiles = sa.table(
        "c19_profiles",
        sa.column("user_id", _user_id_type()),
        sa.column("display_name", sa.String(length=255)),
        sa.column("avatar_ref", sa.String(length=512)),
        sa.column("bio", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    profile_rows: list[dict[str, object]] = []
    for row in bind.execute(
        sa.select(
            users.c.id,
            users.c.username,
            users.c.created_at,
            users.c.updated_at,
        )
    ).mappings():
        display_name = str(row["username"] or "").strip()
        if not display_name:
            continue
        created_at = row["created_at"] or now
        profile_rows.append(
            {
                "user_id": row["id"],
                "display_name": display_name,
                "avatar_ref": None,
                "bio": None,
                "created_at": created_at,
                "updated_at": row["updated_at"] or created_at,
            }
        )
    if profile_rows:
        bind.execute(profiles.insert(), profile_rows)

    memberships = sa.table(
        "org_memberships",
        sa.column("membership_id", sa.String(length=64)),
        sa.column("user_id", sa.String(length=255)),
        sa.column("org_id", sa.String(length=40)),
        sa.column("role", sa.String(length=20)),
        sa.column("status", sa.String(length=20)),
        sa.column("joined_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    organizations = sa.table(
        "organizations",
        sa.column("org_id", sa.String(length=40)),
    )
    affiliations = sa.table(
        "c19_affiliations",
        sa.column("affiliation_id", sa.String(length=64)),
        sa.column("user_id", _user_id_type()),
        sa.column("org_id", sa.String(length=40)),
        sa.column("source_membership_id", sa.String(length=64)),
        sa.column("role", sa.String(length=20)),
        sa.column("status", sa.String(length=20)),
        sa.column("joined_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    source = (
        memberships.join(
            users,
            memberships.c.user_id == sa.cast(users.c.id, sa.String(length=255)),
        )
        .join(profiles, profiles.c.user_id == users.c.id)
        .join(organizations, organizations.c.org_id == memberships.c.org_id)
    )
    affiliation_rows: list[dict[str, object]] = []
    for row in bind.execute(
        sa.select(
            memberships.c.membership_id,
            users.c.id.label("resolved_user_id"),
            memberships.c.org_id,
            memberships.c.role,
            memberships.c.status,
            memberships.c.joined_at,
            memberships.c.created_at,
        ).select_from(source)
    ).mappings():
        membership_id = str(row["membership_id"])
        joined_at = row["joined_at"] or row["created_at"] or now
        affiliation_rows.append(
            {
                "affiliation_id": "c19aff_"
                + sha256(membership_id.encode("utf-8")).hexdigest()[:32],
                "user_id": row["resolved_user_id"],
                "org_id": row["org_id"],
                "source_membership_id": membership_id,
                "role": row["role"],
                "status": row["status"],
                "joined_at": joined_at,
                "created_at": row["created_at"] or joined_at,
                "updated_at": now,
            }
        )
    if affiliation_rows:
        bind.execute(affiliations.insert(), affiliation_rows)


def upgrade() -> None:
    _create_profiles()
    _create_affiliations()
    _create_friend_requests()
    _create_relationships()
    _create_user_blocks()
    _create_conversations()
    _create_conversation_members()
    _create_conversation_user_settings()
    _backfill_profiles_and_affiliations()


def downgrade() -> None:
    op.drop_table("c19_conversation_user_settings")
    op.drop_table("c19_conversation_members")
    op.drop_table("c19_conversations")
    op.drop_table("c19_user_blocks")
    op.drop_table("c19_relationships")
    op.drop_table("c19_friend_requests")
    op.drop_table("c19_affiliations")
    op.drop_table("c19_profiles")

