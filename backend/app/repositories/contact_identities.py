from datetime import datetime

from sqlalchemy.orm import Session

from ..models.contact_identity import ContactIdentityRecord


def get_contact_identity(
    db: Session,
    user_id: str,
) -> ContactIdentityRecord | None:
    return db.get(ContactIdentityRecord, user_id)


def create_contact_identity_record(
    db: Session,
    *,
    user_id: str,
    name: str,
    org_id: str,
    org_name: str,
    title: str,
    role: str,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> ContactIdentityRecord:
    identity = ContactIdentityRecord(
        user_id=user_id,
        name=name,
        org_id=org_id,
        org_name=org_name,
        title=title,
        role=role,
    )
    if created_at is not None:
        identity.created_at = created_at
    if updated_at is not None:
        identity.updated_at = updated_at
    db.add(identity)
    db.flush()
    return identity


def update_contact_identity_record(
    db: Session,
    identity: ContactIdentityRecord,
    *,
    name: str | None = None,
    org_name: str | None = None,
    title: str | None = None,
) -> ContactIdentityRecord:
    if name is not None:
        identity.name = name
    if org_name is not None:
        identity.org_name = org_name
    if title is not None:
        identity.title = title
    db.add(identity)
    db.flush()
    return identity
