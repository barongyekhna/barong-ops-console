from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.org_membership import OrgMembershipRecord


def get_org_membership(
    db: Session,
    membership_id: str,
) -> OrgMembershipRecord | None:
    return db.get(OrgMembershipRecord, membership_id)


def get_membership_by_user_org(
    db: Session,
    *,
    user_id: str,
    org_id: str,
) -> OrgMembershipRecord | None:
    return db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.user_id == user_id,
            OrgMembershipRecord.org_id == org_id,
        )
    )


def get_owner_membership_by_org(
    db: Session,
    *,
    org_id: str,
) -> OrgMembershipRecord | None:
    return db.scalar(
        select(OrgMembershipRecord).where(
            OrgMembershipRecord.org_id == org_id,
            OrgMembershipRecord.role == "owner",
        )
    )


def list_memberships_by_org(
    db: Session,
    *,
    org_id: str,
    active_only: bool = True,
) -> list[OrgMembershipRecord]:
    statement = select(OrgMembershipRecord).where(OrgMembershipRecord.org_id == org_id)
    if active_only:
        statement = statement.where(OrgMembershipRecord.status == "active")
    return list(
        db.scalars(
            statement.order_by(
                OrgMembershipRecord.role,
                OrgMembershipRecord.joined_at,
                OrgMembershipRecord.user_id,
            )
        )
    )


def create_org_membership_record(
    db: Session,
    *,
    membership_id: str,
    user_id: str,
    org_id: str,
    role: str,
    status: str = "active",
    joined_at: datetime | None = None,
) -> OrgMembershipRecord:
    membership = OrgMembershipRecord(
        membership_id=membership_id,
        user_id=user_id,
        org_id=org_id,
        role=role,
        status=status,
    )
    if joined_at is not None:
        membership.joined_at = joined_at
        membership.created_at = joined_at
    db.add(membership)
    db.flush()
    return membership


def update_org_membership_record(
    db: Session,
    membership: OrgMembershipRecord,
    *,
    role: str | None = None,
    status: str | None = None,
    joined_at: datetime | None = None,
) -> OrgMembershipRecord:
    if role is not None:
        membership.role = role
    if status is not None:
        membership.status = status
    if joined_at is not None:
        membership.joined_at = joined_at
    db.add(membership)
    db.flush()
    return membership
