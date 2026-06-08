from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.artifact import Artifact
from ..schemas.artifacts import ArtifactCreate


def list_artifacts(
    db: Session, *, limit: int, offset: int
) -> list[Artifact]:
    return list(
        db.scalars(
            select(Artifact)
            .order_by(Artifact.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_artifact(db: Session, artifact_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact).where(Artifact.artifact_id == artifact_id)
    )


def create_artifact(db: Session, payload: ArtifactCreate) -> Artifact:
    artifact = Artifact(
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
    return artifact
