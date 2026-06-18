from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...repositories.organizations import list_organizations as list_org_records
from ...schemas.common import ListResponse
from ...schemas.organization import Organization, OrganizationMetadata
from .users import require_user_manager

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _record_to_schema(record: OrganizationRecord) -> Organization:
    return Organization(
        org_id=record.org_id,
        org_name=record.org_name,
        org_type=record.org_type,
        owner_user_id=record.owner_user_id,
        status=record.status,
        metadata=OrganizationMetadata.model_validate(record.metadata_json or {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=ListResponse[Organization])
def organizations(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor: User = Depends(require_user_manager),
) -> ListResponse[Organization]:
    del actor
    records = list_org_records(db, limit=limit, offset=offset)
    return ListResponse(
        items=[_record_to_schema(record) for record in records],
        count=len(records),
        limit=limit,
        offset=offset,
    )
