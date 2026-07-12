"""Database queries for C19 identity projections.

Callers are responsible for entering the controlled global-isolation bypass
only after authenticating and validating the actor.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from ...models.c19 import C19AffiliationRecord, C19ProfileRecord
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User


@dataclass(frozen=True, slots=True)
class C19AffiliationBundle:
    affiliation: C19AffiliationRecord
    organization: OrganizationRecord


@dataclass(frozen=True, slots=True)
class C19ProfileBundle:
    profile: C19ProfileRecord
    affiliations: tuple[C19AffiliationBundle, ...]


def _authoritative_membership_join():
    return and_(
        OrgMembershipRecord.membership_id
        == C19AffiliationRecord.source_membership_id,
        OrgMembershipRecord.user_id
        == cast(C19AffiliationRecord.user_id, String),
        OrgMembershipRecord.org_id == C19AffiliationRecord.org_id,
    )


def _load_active_profile_bundles(
    db: Session,
    *,
    user_ids: list[int],
) -> list[C19ProfileBundle]:
    if not user_ids:
        return []

    profiles = list(
        db.scalars(
            select(C19ProfileRecord).where(C19ProfileRecord.user_id.in_(user_ids))
        )
    )
    profiles_by_id = {profile.user_id: profile for profile in profiles}
    affiliation_rows = db.execute(
        select(C19AffiliationRecord, OrganizationRecord)
        .join(
            OrganizationRecord,
            OrganizationRecord.org_id == C19AffiliationRecord.org_id,
        )
        .join(OrgMembershipRecord, _authoritative_membership_join())
        .where(
            C19AffiliationRecord.user_id.in_(user_ids),
            C19AffiliationRecord.status == "active",
            OrgMembershipRecord.status == "active",
            OrganizationRecord.status == "active",
        )
        .order_by(
            C19AffiliationRecord.user_id,
            func.lower(OrganizationRecord.org_name),
            C19AffiliationRecord.org_id,
        )
    ).all()

    affiliations_by_user: dict[int, list[C19AffiliationBundle]] = {
        user_id: [] for user_id in user_ids
    }
    for affiliation, organization in affiliation_rows:
        affiliations_by_user.setdefault(affiliation.user_id, []).append(
            C19AffiliationBundle(
                affiliation=affiliation,
                organization=organization,
            )
        )

    return [
        C19ProfileBundle(
            profile=profiles_by_id[user_id],
            affiliations=tuple(affiliations_by_user.get(user_id, ())),
        )
        for user_id in user_ids
        if user_id in profiles_by_id
    ]


def list_active_profile_bundles(
    db: Session,
    *,
    search: str | None,
    affiliation_org_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[C19ProfileBundle], int]:
    statement = select(
        C19ProfileRecord.user_id,
        C19ProfileRecord.display_name,
    ).join(User, User.id == C19ProfileRecord.user_id).where(
        User.is_active.is_(True),
    )
    if search:
        pattern = f"%{search}%"
        affiliation_match = (
            select(C19AffiliationRecord.affiliation_id)
            .join(
                OrganizationRecord,
                OrganizationRecord.org_id == C19AffiliationRecord.org_id,
            )
            .join(OrgMembershipRecord, _authoritative_membership_join())
            .where(
                C19AffiliationRecord.user_id == C19ProfileRecord.user_id,
                C19AffiliationRecord.status == "active",
                OrgMembershipRecord.status == "active",
                OrganizationRecord.status == "active",
                or_(
                    OrganizationRecord.org_name.ilike(pattern),
                    C19AffiliationRecord.role.ilike(pattern),
                ),
            )
            .correlate(C19ProfileRecord)
            .exists()
        )
        statement = statement.where(
            or_(
                C19ProfileRecord.display_name.ilike(pattern),
                C19ProfileRecord.bio.ilike(pattern),
                affiliation_match,
            )
        )
    if affiliation_org_id:
        # Organization is an optional directory filter, never a prerequisite
        # for appearing in the global C19 directory.
        statement = (
            statement.join(
                C19AffiliationRecord,
                C19AffiliationRecord.user_id == C19ProfileRecord.user_id,
            )
            .join(
                OrganizationRecord,
                OrganizationRecord.org_id == C19AffiliationRecord.org_id,
            )
            .join(OrgMembershipRecord, _authoritative_membership_join())
            .where(
                C19AffiliationRecord.org_id == affiliation_org_id,
                C19AffiliationRecord.status == "active",
                OrgMembershipRecord.status == "active",
                OrganizationRecord.status == "active",
            )
        )

    grouped = statement.group_by(
        C19ProfileRecord.user_id,
        C19ProfileRecord.display_name,
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(grouped.order_by(None).subquery())
        )
        or 0
    )
    rows = db.execute(
        grouped.order_by(
            func.lower(C19ProfileRecord.display_name),
            C19ProfileRecord.user_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    user_ids = [int(row.user_id) for row in rows]
    return _load_active_profile_bundles(db, user_ids=user_ids), total


def get_active_profile_bundle(
    db: Session,
    *,
    user_id: int,
) -> C19ProfileBundle | None:
    is_visible = db.scalar(
        select(C19ProfileRecord.user_id)
        .join(User, User.id == C19ProfileRecord.user_id)
        .where(
            C19ProfileRecord.user_id == user_id,
            User.is_active.is_(True),
        )
        .limit(1)
    )
    if is_visible is None:
        return None
    bundles = _load_active_profile_bundles(db, user_ids=[user_id])
    return bundles[0] if bundles else None


def get_active_profile_bundles(
    db: Session,
    *,
    user_ids: list[int],
) -> dict[int, C19ProfileBundle]:
    if not user_ids:
        return {}
    active_ids = list(
        db.scalars(
            select(C19ProfileRecord.user_id)
            .join(User, User.id == C19ProfileRecord.user_id)
            .where(
                C19ProfileRecord.user_id.in_(user_ids),
                User.is_active.is_(True),
            )
        )
    )
    active_id_set = set(active_ids)
    bundles = _load_active_profile_bundles(
        db,
        user_ids=[user_id for user_id in user_ids if user_id in active_id_set],
    )
    return {bundle.profile.user_id: bundle for bundle in bundles}


__all__ = [
    "C19AffiliationBundle",
    "C19ProfileBundle",
    "get_active_profile_bundle",
    "get_active_profile_bundles",
    "list_active_profile_bundles",
]
