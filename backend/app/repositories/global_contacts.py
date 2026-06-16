from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models.contact_identity import ContactIdentityRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord


@dataclass(frozen=True)
class GlobalContactSourceRow:
    identity: ContactIdentityRecord
    membership: OrgMembershipRecord
    organization: OrganizationRecord | None


def user_has_active_org_membership(
    db: Session,
    *,
    user_id: str,
) -> bool:
    membership_id = db.scalar(
        select(OrgMembershipRecord.membership_id)
        .where(
            OrgMembershipRecord.user_id == user_id,
            OrgMembershipRecord.status == "active",
        )
        .limit(1)
    )
    return membership_id is not None


def list_global_contact_source_rows(db: Session) -> list[GlobalContactSourceRow]:
    statement = (
        select(ContactIdentityRecord, OrgMembershipRecord, OrganizationRecord)
        .join(
            OrgMembershipRecord,
            and_(
                OrgMembershipRecord.user_id == ContactIdentityRecord.user_id,
                OrgMembershipRecord.org_id == ContactIdentityRecord.org_id,
                OrgMembershipRecord.status == "active",
            ),
        )
        .outerjoin(
            OrganizationRecord,
            OrganizationRecord.org_id == ContactIdentityRecord.org_id,
        )
    )

    return [
        GlobalContactSourceRow(
            identity=identity,
            membership=membership,
            organization=organization,
        )
        for identity, membership, organization in db.execute(statement).all()
    ]
