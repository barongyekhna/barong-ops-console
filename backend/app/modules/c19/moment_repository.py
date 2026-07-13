"""Current Barong-side authorization projections for C19 Moments.

Moment content never enters the Barong database.  These queries expose only
the live C18/C19 membership, friendship and block facts needed to narrow the
immutable audience stored by the Record Service.
"""

from __future__ import annotations

from sqlalchemy import String, and_, case, cast, or_, select
from sqlalchemy.orm import Session

from ...models.c19 import (
    C19AffiliationRecord,
    C19ProfileRecord,
    C19RelationshipRecord,
    C19UserBlockRecord,
)
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User
from .block_policy import effective_block_target_condition


def _authoritative_membership_join():
    return and_(
        OrgMembershipRecord.membership_id
        == C19AffiliationRecord.source_membership_id,
        OrgMembershipRecord.user_id
        == cast(C19AffiliationRecord.user_id, String),
        OrgMembershipRecord.org_id == C19AffiliationRecord.org_id,
    )


def _active_affiliation_statement():
    return (
        select(
            C19AffiliationRecord.affiliation_id,
            C19AffiliationRecord.user_id,
            C19AffiliationRecord.org_id,
        )
        .join(User, User.id == C19AffiliationRecord.user_id)
        .join(C19ProfileRecord, C19ProfileRecord.user_id == User.id)
        .join(OrgMembershipRecord, _authoritative_membership_join())
        .join(
            OrganizationRecord,
            OrganizationRecord.org_id == C19AffiliationRecord.org_id,
        )
        .where(
            User.is_active.is_(True),
            C19AffiliationRecord.status == "active",
            OrgMembershipRecord.status == "active",
            OrganizationRecord.status == "active",
        )
    )


def list_active_user_ids(db: Session) -> set[int]:
    """Return active global C19 users, including users without affiliations."""

    statement = select(User.id).where(User.is_active.is_(True))
    return {int(value) for value in db.scalars(statement)}


def list_active_org_ids(db: Session, *, user_id: int) -> set[str]:
    statement = (
        _active_affiliation_statement()
        .with_only_columns(C19AffiliationRecord.org_id)
        .where(C19AffiliationRecord.user_id == user_id)
        .distinct()
    )
    return set(db.scalars(statement))


def resolve_owned_affiliations(
    db: Session,
    *,
    user_id: int,
    affiliation_ids: set[str],
) -> dict[str, str]:
    """Resolve actor-owned active affiliation IDs to authoritative org IDs."""

    if not affiliation_ids:
        return {}
    rows = db.execute(
        _active_affiliation_statement().where(
            C19AffiliationRecord.user_id == user_id,
            C19AffiliationRecord.affiliation_id.in_(affiliation_ids),
        )
    ).all()
    return {
        str(row.affiliation_id): str(row.org_id)
        for row in rows
    }


def list_active_user_ids_for_orgs(
    db: Session,
    *,
    org_ids: set[str],
) -> set[int]:
    if not org_ids:
        return set()
    statement = (
        _active_affiliation_statement()
        .with_only_columns(C19AffiliationRecord.user_id)
        .where(C19AffiliationRecord.org_id.in_(org_ids))
        .distinct()
    )
    return {int(value) for value in db.scalars(statement)}


def list_friend_user_ids(db: Session, *, user_id: int) -> set[int]:
    counterpart = case(
        (
            C19RelationshipRecord.user_low_id == user_id,
            C19RelationshipRecord.user_high_id,
        ),
        else_=C19RelationshipRecord.user_low_id,
    )
    statement = select(counterpart).where(
        C19RelationshipRecord.status == "friends",
        or_(
            C19RelationshipRecord.user_low_id == user_id,
            C19RelationshipRecord.user_high_id == user_id,
        ),
    )
    return {int(value) for value in db.scalars(statement)}


def list_blocked_user_ids(db: Session, *, user_id: int) -> set[int]:
    """Return both sides of every live block involving the actor."""

    counterpart = case(
        (
            C19UserBlockRecord.blocker_user_id == user_id,
            C19UserBlockRecord.blocked_user_id,
        ),
        else_=C19UserBlockRecord.blocker_user_id,
    )
    statement = select(counterpart).where(
        C19UserBlockRecord.status == "active",
        C19UserBlockRecord.is_active.is_(True),
        effective_block_target_condition(
            C19UserBlockRecord.blocker_user_id,
            C19UserBlockRecord.blocked_user_id,
        ),
        or_(
            C19UserBlockRecord.blocker_user_id == user_id,
            C19UserBlockRecord.blocked_user_id == user_id,
        ),
    )
    return {int(value) for value in db.scalars(statement)}


def get_active_organization_names(
    db: Session,
    *,
    org_ids: set[str],
) -> dict[str, str]:
    if not org_ids:
        return {}
    rows = db.execute(
        select(OrganizationRecord.org_id, OrganizationRecord.org_name).where(
            OrganizationRecord.org_id.in_(org_ids),
            OrganizationRecord.status == "active",
        )
    ).all()
    return {str(row.org_id): str(row.org_name) for row in rows}


__all__ = [
    "get_active_organization_names",
    "list_active_org_ids",
    "list_active_user_ids",
    "list_active_user_ids_for_orgs",
    "list_blocked_user_ids",
    "list_friend_user_ids",
    "resolve_owned_affiliations",
]
