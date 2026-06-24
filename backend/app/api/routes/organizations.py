from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...repositories.organizations import (
    get_organization,
    list_organizations as list_org_records,
)
from ...schemas.common import ListResponse
from ...schemas.organization import Organization, OrganizationMetadata
from ...services.data_isolation import without_org_data_isolation
from ..deps import get_current_user

router = APIRouter(prefix="/organizations", tags=["organizations"])
ORGANIZATION_LIST_CACHE_TTL_SECONDS = 3.0
_organization_list_cache_lock = Lock()
_organization_list_cache: dict[tuple[int, int], tuple[float, ListResponse[Organization]]] = {}


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
    actor: User = Depends(get_current_user),
) -> ListResponse[Organization]:
    if not is_owner_role(actor.role):
        actor_org_id = (actor.organization_id or "").strip()
        records: list[OrganizationRecord] = []
        if actor_org_id:
            organization = get_organization(db, actor_org_id)
            if organization is not None and organization.status != "deleted":
                records = [organization]
        page = records[offset : offset + limit]
        return ListResponse(
            items=[_record_to_schema(record) for record in page],
            count=len(records),
            limit=limit,
            offset=offset,
        )

    cache_key = (limit, offset)
    now = monotonic()
    with _organization_list_cache_lock:
        cached = _organization_list_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    with without_org_data_isolation():
        records = list_org_records(db, limit=limit, offset=offset)
    response = ListResponse(
        items=[_record_to_schema(record) for record in records],
        count=len(records),
        limit=limit,
        offset=offset,
    )
    with _organization_list_cache_lock:
        _organization_list_cache[cache_key] = (
            monotonic() + ORGANIZATION_LIST_CACHE_TTL_SECONDS,
            response.model_copy(deep=True),
        )
    return response
