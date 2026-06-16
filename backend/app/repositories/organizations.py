from sqlalchemy.orm import Session

from ..models.organization import OrganizationRecord


def get_organization(
    db: Session,
    org_id: str,
) -> OrganizationRecord | None:
    return db.get(OrganizationRecord, org_id)


def create_organization_record(
    db: Session,
    *,
    org_id: str,
    org_name: str,
    org_type: str,
    owner_user_id: str,
    metadata: dict[str, object],
) -> OrganizationRecord:
    organization = OrganizationRecord(
        org_id=org_id,
        org_name=org_name,
        org_type=org_type,
        owner_user_id=owner_user_id,
        status="active",
        metadata_json=metadata,
    )
    db.add(organization)
    db.flush()
    return organization


def update_organization_record(
    db: Session,
    organization: OrganizationRecord,
    *,
    org_name: str | None = None,
    org_type: str | None = None,
    metadata: dict[str, object] | None = None,
    status: str | None = None,
) -> OrganizationRecord:
    if org_name is not None:
        organization.org_name = org_name
    if org_type is not None:
        organization.org_type = org_type
    if metadata is not None:
        organization.metadata_json = metadata
    if status is not None:
        organization.status = status
    db.add(organization)
    db.flush()
    return organization
