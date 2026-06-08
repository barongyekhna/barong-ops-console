from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.artifacts import (
    create_artifact,
    get_artifact,
    list_artifacts,
)
from ...repositories.jobs import get_job
from ...repositories.registry import get_module
from ...schemas.artifacts import ArtifactCreate, ArtifactResponse
from ...schemas.common import ListResponse
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, get_current_user

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("", response_model=ListResponse[ArtifactResponse])
def artifacts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ListResponse[ArtifactResponse]:
    del user
    items = list_artifacts(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def artifact_detail(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactResponse:
    del user
    artifact = get_artifact(db, artifact_id)
    if artifact is None:
        raise not_found("Artifact", artifact_id)
    return ArtifactResponse.model_validate(artifact)


@router.post(
    "",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
def artifact_create(
    payload: ArtifactCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactResponse:
    if get_artifact(db, payload.artifact_id) is not None:
        raise conflict("Artifact", payload.artifact_id)
    if get_job(db, payload.job_id) is None:
        raise invalid_reference("Artifact job_id is not registered.")
    if get_module(db, payload.module_key) is None:
        raise invalid_reference("Artifact module_key is not registered.")
    artifact = create_artifact(db, payload)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="artifact.register_demo",
        target_type="artifact",
        target_id=payload.artifact_id,
        job_id=payload.job_id,
        details={
            "status": payload.status,
            "storage": "metadata_only",
        },
    )
    db.refresh(artifact)
    return ArtifactResponse.model_validate(artifact)
