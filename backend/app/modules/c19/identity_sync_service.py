"""Transactional projection sync from authoritative users and memberships."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...models.c19 import C19AffiliationRecord, C19ProfileRecord
from ...models.org_membership import OrgMembershipRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation


class C19IdentitySyncError(ValueError):
    pass


def _membership_user_id(membership: OrgMembershipRecord) -> int:
    normalized = membership.user_id.strip()
    try:
        user_id = int(normalized)
    except (TypeError, ValueError):
        raise C19IdentitySyncError(
            "C19 affiliation source membership has an invalid user_id."
        ) from None
    if str(user_id) != normalized:
        raise C19IdentitySyncError(
            "C19 affiliation source membership has a non-canonical user_id."
        )
    return user_id


def sync_profile_for_user(db: Session, *, user: User) -> C19ProfileRecord:
    """Ensure a profile exists without overwriting user-managed display data."""

    with without_org_data_isolation():
        profile = db.get(C19ProfileRecord, user.id)
        if profile is None:
            display_name = user.username.strip()
            if not display_name:
                raise C19IdentitySyncError(
                    "C19 profile requires a non-empty authoritative username."
                )
            profile = C19ProfileRecord(
                user_id=user.id,
                display_name=display_name,
            )
            db.add(profile)
            db.flush()
        return profile


def sync_affiliation_from_membership(
    db: Session,
    *,
    membership: OrgMembershipRecord,
    user: User | None = None,
) -> C19AffiliationRecord:
    """Project exactly one authoritative membership without inferring a title."""

    with without_org_data_isolation():
        user_id = _membership_user_id(membership)
        resolved_user = user if user is not None else db.get(User, user_id)
        if resolved_user is None or resolved_user.id != user_id:
            raise C19IdentitySyncError(
                "C19 affiliation source membership user does not exist."
            )
        sync_profile_for_user(db, user=resolved_user)

        matches = list(
            db.scalars(
                select(C19AffiliationRecord).where(
                    or_(
                        C19AffiliationRecord.source_membership_id
                        == membership.membership_id,
                        (
                            C19AffiliationRecord.user_id == user_id
                        )
                        & (C19AffiliationRecord.org_id == membership.org_id),
                    )
                )
            )
        )
        if len({record.affiliation_id for record in matches}) > 1:
            raise C19IdentitySyncError(
                "C19 affiliation source and user/org projections conflict."
            )
        affiliation = matches[0] if matches else None
        effective_status = (
            "active"
            if resolved_user.is_active and membership.status == "active"
            else "suspended"
        )
        if affiliation is None:
            affiliation = C19AffiliationRecord(
                user_id=user_id,
                org_id=membership.org_id,
                source_membership_id=membership.membership_id,
                role=membership.role,
                status=effective_status,
                joined_at=membership.joined_at,
            )
            db.add(affiliation)
        else:
            if (
                affiliation.user_id != user_id
                or affiliation.org_id != membership.org_id
            ):
                raise C19IdentitySyncError(
                    "C19 affiliation cannot be moved to another user or organization."
                )
            affiliation.source_membership_id = membership.membership_id
            affiliation.role = membership.role
            affiliation.status = effective_status
            affiliation.joined_at = membership.joined_at
        db.flush()
        return affiliation


def sync_user_identity(db: Session, *, user: User) -> C19ProfileRecord:
    """Synchronize one user and every authoritative membership in one transaction."""

    with without_org_data_isolation():
        profile = sync_profile_for_user(db, user=user)
        memberships = list(
            db.scalars(
                select(OrgMembershipRecord).where(
                    OrgMembershipRecord.user_id == str(user.id)
                )
            )
        )
        authoritative_membership_ids = {
            membership.membership_id for membership in memberships
        }
        for membership in memberships:
            sync_affiliation_from_membership(
                db,
                membership=membership,
                user=user,
            )

        projected = list(
            db.scalars(
                select(C19AffiliationRecord).where(
                    C19AffiliationRecord.user_id == user.id
                )
            )
        )
        for affiliation in projected:
            if (
                not user.is_active
                or affiliation.source_membership_id
                not in authoritative_membership_ids
            ):
                affiliation.status = "suspended"
        db.flush()
        return profile


__all__ = [
    "C19IdentitySyncError",
    "sync_affiliation_from_membership",
    "sync_profile_for_user",
    "sync_user_identity",
]
