from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...schemas.live_gate import (
    LiveGatePolicyInput,
    LiveGatePolicyRead,
    PreLiveValidationReport,
    ProductionReadinessReport,
    RollbackGuardDecision,
)
from ...services.canary_rollout import CanaryRolloutSystem
from ...services.live_gating_controller import PLATFORM_ORG_ID, LiveGatingController
from ...services.live_rollback_guard import LiveRollbackGuard
from ...services.pre_live_validation import PreLiveValidationEngine
from ...services.production_readiness import ProductionReadinessEngine
from ..deps import require_rbac

router = APIRouter(prefix="/live-gate", tags=["live-gate"])


class CanaryRolloutUpsert(BaseModel):
    scope_type: Literal["global", "org", "module"]
    scope_key: str = Field(min_length=1, max_length=180)
    stage: Literal["mock", "staging", "live"] = "live"
    enabled: bool = False
    percentage: int = Field(default=0, ge=0, le=100)
    org_ids: tuple[str, ...] = Field(default_factory=tuple)
    module_ids: tuple[str, ...] = Field(default_factory=tuple)


class CanaryRolloutRead(CanaryRolloutUpsert):
    rollout_id: str
    org_id: str


class RollbackFailureRequest(BaseModel):
    environment: str = Field(min_length=1, max_length=50)
    service: str = Field(min_length=1, max_length=80)
    current_version: str | None = Field(default=None, max_length=180)
    previous_version: str | None = Field(default=None, max_length=180)
    image_digest: str | None = Field(default=None, max_length=255)
    db_revision: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=700)


class RollbackConsistencyRequest(BaseModel):
    environment: str = Field(min_length=1, max_length=50)
    service: str = Field(min_length=1, max_length=80)
    expected_image_digest: str | None = Field(default=None, max_length=255)
    expected_db_revision: str | None = Field(default=None, max_length=128)


class RollbackRestoreRequest(BaseModel):
    environment: str = Field(min_length=1, max_length=50)
    service: str = Field(min_length=1, max_length=80)


@router.get("/readiness", response_model=PreLiveValidationReport)
def pre_live_readiness(
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> PreLiveValidationReport:
    del user
    return PreLiveValidationEngine(db).run()


@router.get("/production-readiness", response_model=ProductionReadinessReport)
def production_readiness(
    ci_status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> ProductionReadinessReport:
    del user
    return ProductionReadinessEngine(db, ci_status=ci_status).run()


@router.get("/policies", response_model=list[LiveGatePolicyRead])
def list_live_gate_policies(
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> list[LiveGatePolicyRead]:
    del user
    return LiveGatingController(db).list_policies(org_id=org_id)


@router.post("/policies", response_model=LiveGatePolicyRead)
def upsert_live_gate_policy(
    payload: LiveGatePolicyInput,
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> LiveGatePolicyRead:
    del user
    try:
        result = LiveGatingController(db).upsert_policy(org_id=org_id, payload=payload)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


@router.post("/canary", response_model=CanaryRolloutRead)
def upsert_canary_rollout(
    payload: CanaryRolloutUpsert,
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> CanaryRolloutRead:
    del user
    try:
        record = CanaryRolloutSystem(db).upsert_rule(
            org_id=org_id,
            scope_type=payload.scope_type,
            scope_key=payload.scope_key,
            stage=payload.stage,
            enabled=payload.enabled,
            percentage=payload.percentage,
            org_ids=payload.org_ids,
            module_ids=payload.module_ids,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    return CanaryRolloutRead(
        rollout_id=record.rollout_id,
        org_id=record.org_id,
        scope_type=record.scope_type,  # type: ignore[arg-type]
        scope_key=record.scope_key,
        stage=record.stage,  # type: ignore[arg-type]
        enabled=record.enabled,
        percentage=record.percentage,
        org_ids=tuple(record.org_ids or ()),
        module_ids=tuple(record.module_ids or ()),
    )


@router.post("/rollback/failure", response_model=RollbackGuardDecision)
def record_rollback_failure(
    payload: RollbackFailureRequest,
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> RollbackGuardDecision:
    del user
    result = LiveRollbackGuard(db).record_failure(
        org_id=org_id,
        environment=payload.environment,
        service=payload.service,
        current_version=payload.current_version,
        previous_version=payload.previous_version,
        image_digest=payload.image_digest,
        db_revision=payload.db_revision,
        reason=payload.reason,
    )
    db.commit()
    return result


@router.post("/rollback/consistency", response_model=RollbackGuardDecision)
def verify_rollback_consistency(
    payload: RollbackConsistencyRequest,
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> RollbackGuardDecision:
    del user
    result = LiveRollbackGuard(db).verify_consistency(
        org_id=org_id,
        environment=payload.environment,
        service=payload.service,
        expected_image_digest=payload.expected_image_digest,
        expected_db_revision=payload.expected_db_revision,
    )
    db.commit()
    return result


@router.post("/rollback/restore", response_model=RollbackGuardDecision)
def restore_previous_version(
    payload: RollbackRestoreRequest,
    org_id: str = Query(default=PLATFORM_ORG_ID),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("GOVERNANCE", "admin")),
) -> RollbackGuardDecision:
    del user
    result = LiveRollbackGuard(db).restore_previous_version(
        org_id=org_id,
        environment=payload.environment,
        service=payload.service,
    )
    db.commit()
    return result
