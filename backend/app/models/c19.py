from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


def _user_id_type() -> BigInteger:
    return BigInteger().with_variant(Integer, "sqlite")


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex}"


def generate_c19_affiliation_id() -> str:
    return _new_id("c19aff_")


def generate_c19_friend_request_id() -> str:
    return _new_id("c19frq_")


def generate_c19_relationship_id() -> str:
    return _new_id("c19rel_")


def generate_c19_user_block_id() -> str:
    return _new_id("c19blk_")


def generate_c19_conversation_member_id() -> str:
    return _new_id("c19mem_")


class C19ProfileRecord(Base):
    """One communication profile per authenticated platform user.

    Organization membership is deliberately normalized into C19AffiliationRecord;
    this table has no primary-organization or job-title snapshot.
    """

    __tablename__ = "c19_profiles"
    __table_args__ = (
        CheckConstraint(
            "length(trim(display_name)) > 0",
            name="display_name_not_blank",
        ),
        Index("ix_c19_profiles_display_name", "display_name"),
        Index("ix_c19_profiles_updated_at", "updated_at"),
    )

    user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19AffiliationRecord(Base):
    """Communication-visible projection of every C18 organization membership."""

    __tablename__ = "c19_affiliations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="role_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended')",
            name="status_valid",
        ),
        UniqueConstraint(
            "user_id",
            "org_id",
            name="uq_c19_affiliations_user_id_org_id",
        ),
        UniqueConstraint(
            "source_membership_id",
            name="uq_c19_affiliations_source_membership_id",
        ),
        UniqueConstraint(
            "affiliation_id",
            "user_id",
            "org_id",
            name="uq_c19_affiliations_identity_scope",
        ),
        Index("ix_c19_affiliations_user_id_status", "user_id", "status"),
        Index("ix_c19_affiliations_org_id_status", "org_id", "status"),
        Index("ix_c19_affiliations_updated_at", "updated_at"),
    )

    affiliation_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=generate_c19_affiliation_id,
    )
    user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_membership_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("org_memberships.membership_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19FriendRequestRecord(Base):
    __tablename__ = "c19_friend_requests"
    __table_args__ = (
        CheckConstraint(
            "requester_user_id <> addressee_user_id",
            name="participants_distinct",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint(
            "length(trim(pair_key)) > 0",
            name="pair_key_not_blank",
        ),
        UniqueConstraint(
            "pair_key",
            name="uq_c19_friend_requests_pair_key",
        ),
        Index(
            "ix_c19_friend_requests_addressee_status",
            "addressee_user_id",
            "status",
        ),
        Index(
            "ix_c19_friend_requests_requester_status",
            "requester_user_id",
            "status",
        ),
        Index("ix_c19_friend_requests_status_created_at", "status", "created_at"),
    )

    request_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=generate_c19_friend_request_id,
    )
    pair_key: Mapped[str] = mapped_column(String(128), nullable=False)
    requester_user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    addressee_user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    request_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19RelationshipRecord(Base):
    __tablename__ = "c19_relationships"
    __table_args__ = (
        CheckConstraint(
            "user_low_id < user_high_id",
            name="canonical_participant_order",
        ),
        CheckConstraint(
            "status IN ('friends', 'removed')",
            name="status_valid",
        ),
        UniqueConstraint(
            "pair_key",
            name="uq_c19_relationships_pair_key",
        ),
        UniqueConstraint(
            "user_low_id",
            "user_high_id",
            name="uq_c19_relationships_canonical_pair",
        ),
        Index("ix_c19_relationships_user_low_status", "user_low_id", "status"),
        Index("ix_c19_relationships_user_high_status", "user_high_id", "status"),
        Index("ix_c19_relationships_updated_at", "updated_at"),
    )

    relationship_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=generate_c19_relationship_id,
    )
    pair_key: Mapped[str] = mapped_column(String(128), nullable=False)
    user_low_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_high_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="friends",
        server_default="friends",
    )
    origin_request_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("c19_friend_requests.request_id", ondelete="SET NULL"),
        nullable=True,
    )
    established_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19UserBlockRecord(Base):
    """Directed, blocker-owned privacy state; never visible to the blocked user."""

    __tablename__ = "c19_user_blocks"
    __table_args__ = (
        CheckConstraint(
            "blocker_user_id <> blocked_user_id",
            name="participants_distinct",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="status_valid",
        ),
        CheckConstraint(
            "(status = 'active' AND is_active = true AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND is_active = false "
            "AND revoked_at IS NOT NULL)",
            name="lifecycle_consistent",
        ),
        UniqueConstraint(
            "blocker_user_id",
            "blocked_user_id",
            name="uq_c19_user_blocks_blocker_blocked",
        ),
        Index("ix_c19_user_blocks_blocker_status", "blocker_user_id", "status"),
        Index("ix_c19_user_blocks_blocked_status", "blocked_user_id", "status"),
        Index("ix_c19_user_blocks_updated_at", "updated_at"),
    )

    block_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=generate_c19_user_block_id,
    )
    blocker_user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    blocked_user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19ConversationRecord(Base):
    __tablename__ = "c19_conversations"
    __table_args__ = (
        CheckConstraint(
            "type IN ('direct', 'group')",
            name="type_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'archived', 'closed')",
            name="status_valid",
        ),
        CheckConstraint(
            "(type = 'direct' AND direct_pair_key IS NOT NULL) "
            "OR (type = 'group' AND direct_pair_key IS NULL)",
            name="direct_pair_key_matches_type",
        ),
        CheckConstraint(
            "title IS NULL OR length(trim(title)) > 0",
            name="title_not_blank",
        ),
        UniqueConstraint(
            "direct_pair_key",
            name="uq_c19_conversations_direct_pair_key",
        ),
        Index("ix_c19_conversations_type_status", "type", "status"),
        Index("ix_c19_conversations_updated_at", "updated_at"),
    )

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_type: Mapped[str] = mapped_column(
        "type",
        String(20),
        nullable=False,
    )
    direct_pair_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        _user_id_type(),
        ForeignKey("c19_profiles.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19ConversationMemberRecord(Base):
    """Participant authorization metadata; message position lives remotely."""

    __tablename__ = "c19_conversation_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["affiliation_id", "user_id", "org_id_at_join"],
            [
                "c19_affiliations.affiliation_id",
                "c19_affiliations.user_id",
                "c19_affiliations.org_id",
            ],
            name="fk_c19_conversation_members_affiliation_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id"],
            ["c19_profiles.user_id"],
            name="fk_c19_conversation_members_user_profile",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(affiliation_id IS NULL AND org_id_at_join IS NULL) OR "
            "(affiliation_id IS NOT NULL AND org_id_at_join IS NOT NULL)",
            name="affiliation_snapshot_consistent",
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="role_valid",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'left', 'removed', 'banned')",
            name="status_valid",
        ),
        CheckConstraint(
            "(status IN ('invited', 'active') AND left_at IS NULL) "
            "OR (status IN ('left', 'removed', 'banned') AND left_at IS NOT NULL)",
            name="departure_state_consistent",
        ),
        UniqueConstraint(
            "conversation_id",
            "user_id",
            name="uq_c19_conversation_members_conversation_user",
        ),
        Index(
            "ix_c19_conversation_members_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_c19_conversation_members_conversation_status",
            "conversation_id",
            "status",
        ),
        Index(
            "ix_c19_conversation_members_org_status",
            "org_id_at_join",
            "status",
        ),
    )

    member_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=generate_c19_conversation_member_id,
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("c19_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    affiliation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int] = mapped_column(_user_id_type(), nullable=False)
    org_id_at_join: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="member",
        server_default="member",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class C19ConversationUserSettingRecord(Base):
    """Per-user conversation presentation and notification preferences only."""

    __tablename__ = "c19_conversation_user_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            [
                "c19_conversation_members.conversation_id",
                "c19_conversation_members.user_id",
            ],
            name="fk_c19_conversation_user_settings_member",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "notification_level IN ('all', 'mentions', 'none')",
            name="notification_level_valid",
        ),
        Index(
            "ix_c19_conversation_user_settings_user_archived",
            "user_id",
            "is_archived",
        ),
        Index(
            "ix_c19_conversation_user_settings_user_pinned",
            "user_id",
            "is_pinned",
        ),
        Index("ix_c19_conversation_user_settings_updated_at", "updated_at"),
    )

    conversation_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        _user_id_type(),
        primary_key=True,
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    is_muted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    notification_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="all",
        server_default="all",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "C19AffiliationRecord",
    "C19ConversationMemberRecord",
    "C19ConversationRecord",
    "C19ConversationUserSettingRecord",
    "C19FriendRequestRecord",
    "C19ProfileRecord",
    "C19RelationshipRecord",
    "C19UserBlockRecord",
    "generate_c19_affiliation_id",
    "generate_c19_conversation_member_id",
    "generate_c19_friend_request_id",
    "generate_c19_relationship_id",
    "generate_c19_user_block_id",
]
