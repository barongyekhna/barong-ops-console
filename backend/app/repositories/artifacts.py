from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.artifact import Artifact
from ..schemas.artifacts import ArtifactCreate
from ..services.event_collector import record_file_operation
from .tenant import current_tenant_org_id, tenant_org_id_for_create


def list_artifacts(
    db: Session, *, limit: int, offset: int
) -> list[Artifact]:
    org_id = current_tenant_org_id()
    rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.org_id == org_id)
            .order_by(Artifact.id.desc())
            .limit(limit + offset)
        )
    )
    artifacts = rows[offset : offset + limit]
    record_file_operation(
        action="read",
        storage_provider="artifact_registry",
        payload={"operation": "list_artifacts", "count": len(artifacts)},
    )
    return artifacts


def get_artifact(db: Session, artifact_id: str) -> Artifact | None:
    org_id = current_tenant_org_id()
    artifact = db.scalar(
        select(Artifact).where(
            Artifact.artifact_id == artifact_id,
            Artifact.org_id == org_id,
        )
    )
    record_file_operation(
        action="read",
        storage_provider=(
            artifact.storage_provider if artifact is not None else "artifact_registry"
        ),
        storage_ref=artifact.storage_ref if artifact is not None else None,
        status="success" if artifact is not None else "failed",
        payload={"operation": "get_artifact", "artifact_id": artifact_id},
    )
    return artifact


def create_artifact(db: Session, payload: ArtifactCreate) -> Artifact:
    artifact = Artifact(
        org_id=tenant_org_id_for_create(),
        artifact_id=payload.artifact_id,
        job_id=payload.job_id,
        module_id=payload.module_key,
        artifact_type=payload.artifact_type,
        name=payload.name,
        storage_provider=payload.storage_provider,
        storage_ref=payload.storage_ref,
        content_hash=payload.content_hash,
        schema_version=payload.schema_version,
        version=payload.version,
        status=payload.status,
        artifact_metadata=payload.metadata,
    )
    db.add(artifact)
    record_file_operation(
        action="write",
        storage_provider=payload.storage_provider,
        storage_ref=payload.storage_ref,
        payload={
            "operation": "create_artifact",
            "artifact_id": payload.artifact_id,
            "job_id": payload.job_id,
            "module_key": payload.module_key,
        },
    )
    return artifact
