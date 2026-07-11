from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from ...models.c19 import (
    C19AffiliationRecord,
    C19ConversationMemberRecord,
    C19ConversationRecord,
    C19ConversationUserSettingRecord,
    C19UserBlockRecord,
)
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User


@dataclass(frozen=True)
class ConversationListRow:
    conversation: C19ConversationRecord
    actor_member: C19ConversationMemberRecord
    settings: C19ConversationUserSettingRecord | None
    active_member_count: int


def list_authorized_affiliations(
    db: Session,
    *,
    user_id: int,
    for_update: bool = False,
) -> list[C19AffiliationRecord]:
    """Return only projections still authorized by current C18 source records."""

    statement = (
        select(C19AffiliationRecord)
        .join(User, User.id == C19AffiliationRecord.user_id)
        .join(
            OrgMembershipRecord,
            and_(
                OrgMembershipRecord.membership_id
                == C19AffiliationRecord.source_membership_id,
                OrgMembershipRecord.user_id
                == cast(C19AffiliationRecord.user_id, String(255)),
                OrgMembershipRecord.org_id == C19AffiliationRecord.org_id,
            ),
        )
        .join(
            OrganizationRecord,
            OrganizationRecord.org_id == C19AffiliationRecord.org_id,
        )
        .where(
            C19AffiliationRecord.user_id == user_id,
            C19AffiliationRecord.status == "active",
            User.is_active.is_(True),
            OrgMembershipRecord.status == "active",
            OrganizationRecord.status == "active",
        )
        .order_by(C19AffiliationRecord.affiliation_id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(db.scalars(statement))


def list_authorized_affiliation_ids_for_users(
    db: Session,
    *,
    user_ids: set[int],
) -> set[str]:
    """Bulk-resolve current C18/C19 affiliations for message fan-out."""

    if not user_ids:
        return set()
    statement = (
        select(C19AffiliationRecord.affiliation_id)
        .join(User, User.id == C19AffiliationRecord.user_id)
        .join(
            OrgMembershipRecord,
            and_(
                OrgMembershipRecord.membership_id
                == C19AffiliationRecord.source_membership_id,
                OrgMembershipRecord.user_id
                == cast(C19AffiliationRecord.user_id, String(255)),
                OrgMembershipRecord.org_id == C19AffiliationRecord.org_id,
            ),
        )
        .join(
            OrganizationRecord,
            OrganizationRecord.org_id == C19AffiliationRecord.org_id,
        )
        .where(
            C19AffiliationRecord.user_id.in_(user_ids),
            C19AffiliationRecord.status == "active",
            User.is_active.is_(True),
            OrgMembershipRecord.status == "active",
            OrganizationRecord.status == "active",
        )
    )
    return set(db.scalars(statement))


def active_block_exists_between(
    db: Session,
    *,
    first_user_id: int,
    second_user_id: int,
) -> bool:
    block_id = db.scalar(
        select(C19UserBlockRecord.block_id)
        .where(
            C19UserBlockRecord.is_active.is_(True),
            C19UserBlockRecord.status == "active",
            or_(
                and_(
                    C19UserBlockRecord.blocker_user_id == first_user_id,
                    C19UserBlockRecord.blocked_user_id == second_user_id,
                ),
                and_(
                    C19UserBlockRecord.blocker_user_id == second_user_id,
                    C19UserBlockRecord.blocked_user_id == first_user_id,
                ),
            ),
        )
        .limit(1)
    )
    return block_id is not None


def active_block_exists_across(
    db: Session,
    *,
    candidate_user_ids: set[int],
    participant_user_ids: set[int],
) -> bool:
    if not candidate_user_ids or not participant_user_ids:
        return False
    block_id = db.scalar(
        select(C19UserBlockRecord.block_id)
        .where(
            C19UserBlockRecord.is_active.is_(True),
            C19UserBlockRecord.status == "active",
            C19UserBlockRecord.blocker_user_id
            != C19UserBlockRecord.blocked_user_id,
            or_(
                and_(
                    C19UserBlockRecord.blocker_user_id.in_(candidate_user_ids),
                    C19UserBlockRecord.blocked_user_id.in_(participant_user_ids),
                ),
                and_(
                    C19UserBlockRecord.blocked_user_id.in_(candidate_user_ids),
                    C19UserBlockRecord.blocker_user_id.in_(participant_user_ids),
                ),
            ),
        )
        .limit(1)
    )
    return block_id is not None


def get_conversation(
    db: Session,
    *,
    conversation_id: str,
    for_update: bool = False,
) -> C19ConversationRecord | None:
    statement = select(C19ConversationRecord).where(
        C19ConversationRecord.conversation_id == conversation_id
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def get_direct_conversation_by_pair(
    db: Session,
    *,
    direct_pair_key: str,
    for_update: bool = False,
) -> C19ConversationRecord | None:
    statement = select(C19ConversationRecord).where(
        C19ConversationRecord.conversation_type == "direct",
        C19ConversationRecord.direct_pair_key == direct_pair_key,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def get_conversation_member(
    db: Session,
    *,
    conversation_id: str,
    user_id: int,
    for_update: bool = False,
) -> C19ConversationMemberRecord | None:
    statement = select(C19ConversationMemberRecord).where(
        C19ConversationMemberRecord.conversation_id == conversation_id,
        C19ConversationMemberRecord.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_conversation_members(
    db: Session,
    *,
    conversation_id: str,
    active_only: bool = False,
    for_update: bool = False,
) -> list[C19ConversationMemberRecord]:
    statement = select(C19ConversationMemberRecord).where(
        C19ConversationMemberRecord.conversation_id == conversation_id
    )
    if active_only:
        statement = statement.where(C19ConversationMemberRecord.status == "active")
    if for_update:
        statement = statement.order_by(
            C19ConversationMemberRecord.user_id,
        ).with_for_update()
    else:
        statement = statement.order_by(
            C19ConversationMemberRecord.joined_at,
            C19ConversationMemberRecord.user_id,
        )
    return list(db.scalars(statement))


def get_conversation_settings(
    db: Session,
    *,
    conversation_id: str,
    user_id: int,
    for_update: bool = False,
) -> C19ConversationUserSettingRecord | None:
    statement = select(C19ConversationUserSettingRecord).where(
        C19ConversationUserSettingRecord.conversation_id == conversation_id,
        C19ConversationUserSettingRecord.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_actor_conversations(
    db: Session,
    *,
    user_id: int,
    authorized_affiliation_ids: set[str],
    limit: int,
    offset: int,
) -> tuple[list[ConversationListRow], int]:
    actor_member = aliased(C19ConversationMemberRecord)
    counted_member = aliased(C19ConversationMemberRecord)
    active_count = (
        select(func.count(counted_member.member_id))
        .where(
            counted_member.conversation_id
            == C19ConversationRecord.conversation_id,
            counted_member.status == "active",
        )
        .correlate(C19ConversationRecord)
        .scalar_subquery()
    )
    base_filters = (
        actor_member.user_id == user_id,
        actor_member.status == "active",
        actor_member.affiliation_id.in_(authorized_affiliation_ids),
        C19ConversationRecord.status != "closed",
    )
    total = int(
        db.scalar(
            select(func.count(C19ConversationRecord.conversation_id))
            .join(
                actor_member,
                actor_member.conversation_id
                == C19ConversationRecord.conversation_id,
            )
            .where(*base_filters)
        )
        or 0
    )
    statement = (
        select(
            C19ConversationRecord,
            actor_member,
            C19ConversationUserSettingRecord,
            active_count.label("active_member_count"),
        )
        .join(
            actor_member,
            actor_member.conversation_id == C19ConversationRecord.conversation_id,
        )
        .outerjoin(
            C19ConversationUserSettingRecord,
            and_(
                C19ConversationUserSettingRecord.conversation_id
                == C19ConversationRecord.conversation_id,
                C19ConversationUserSettingRecord.user_id == user_id,
            ),
        )
        .where(*base_filters)
        .order_by(
            C19ConversationRecord.updated_at.desc(),
            C19ConversationRecord.conversation_id,
        )
        .offset(offset)
        .limit(limit)
    )
    rows = [
        ConversationListRow(
            conversation=row[0],
            actor_member=row[1],
            settings=row[2],
            active_member_count=int(row[3]),
        )
        for row in db.execute(statement).all()
    ]
    return rows, total


def add_conversation(db: Session, conversation: C19ConversationRecord) -> None:
    db.add(conversation)


def add_conversation_member(
    db: Session,
    member: C19ConversationMemberRecord,
) -> None:
    db.add(member)


def add_conversation_settings(
    db: Session,
    settings: C19ConversationUserSettingRecord,
) -> None:
    db.add(settings)


__all__ = [
    "ConversationListRow",
    "active_block_exists_across",
    "active_block_exists_between",
    "add_conversation",
    "add_conversation_member",
    "add_conversation_settings",
    "get_conversation",
    "get_conversation_member",
    "get_conversation_settings",
    "get_direct_conversation_by_pair",
    "list_actor_conversations",
    "list_authorized_affiliation_ids_for_users",
    "list_authorized_affiliations",
    "list_conversation_members",
]
