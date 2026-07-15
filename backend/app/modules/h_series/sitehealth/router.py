"""FastAPI control-plane and machine-ingest endpoints for H site health."""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....core.roles import is_super_admin_role
from ....db.session import get_db
from ....models.user import User
from ....services.permission_service import resolve_current_user_permission_info
from . import service
from .models import HHealthFinding, HHealthRun

PERMISSION_READ = "h.site_health.read"
PERMISSION_MANAGE = "h.site_health.manage"

router = APIRouter(prefix="/h", tags=["h-site-health"])


def _require_h_permission(permission_key: str):
    """Owner and super-admin bypass; manage implicitly grants read."""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        permissions = resolve_current_user_permission_info(db, user, request=request)
        allowed_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_keys.add(PERMISSION_MANAGE)
        if (
            permissions.is_owner_full_access
            or is_super_admin_role(user.role)
            or allowed_keys.intersection(permissions.permission_keys)
        ):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


class RunItem(BaseModel):
    id: UUID
    trigger: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    urls_total: int
    urls_ok: int
    urls_broken: int
    urls_slow: int
    avg_response_ms: int | None
    p95_response_ms: int | None
    sitemap_ok: bool
    homepage_ok: bool
    summary_json: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class FindingItem(BaseModel):
    id: UUID
    run_id: UUID
    finding_type: str
    url: str
    status_code: int | None
    response_ms: int | None
    detail: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class RunsResponse(BaseModel):
    runs: list[RunItem]


class RunDetail(RunItem):
    findings: list[FindingItem]


class FindingsResponse(BaseModel):
    items: list[FindingItem]
    total: int


class FindingActionRequest(BaseModel):
    action: str = Field(pattern="^(acknowledge|resolve|reopen)$")


class IngestSummary(BaseModel):
    urls_total: int = Field(ge=0)
    urls_ok: int = Field(ge=0)
    urls_broken: int = Field(ge=0)
    urls_slow: int = Field(ge=0)
    avg_response_ms: int | None = Field(default=None, ge=0)
    p95_response_ms: int | None = Field(default=None, ge=0)
    sitemap_ok: bool
    homepage_ok: bool


class IngestFinding(BaseModel):
    finding_type: str = Field(
        pattern="^(broken_link|slow_page|sitemap_error|homepage_error)$"
    )
    url: str = Field(min_length=1, max_length=2048)
    status_code: int | None = None
    response_ms: int | None = Field(default=None, ge=0)
    detail: str | None = None


class IngestRequest(BaseModel):
    run_id: UUID | None = None
    status: str = Field(pattern="^(completed|failed)$")
    error: str | None = None
    summary: IngestSummary
    findings: list[IngestFinding] = Field(default_factory=list)


class IngestResponse(BaseModel):
    run_id: UUID
    deduped: bool


def _run_item(run: HHealthRun) -> RunItem:
    return RunItem(
        id=run.id,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        urls_total=run.urls_total,
        urls_ok=run.urls_ok,
        urls_broken=run.urls_broken,
        urls_slow=run.urls_slow,
        avg_response_ms=run.avg_response_ms,
        p95_response_ms=run.p95_response_ms,
        sitemap_ok=run.sitemap_ok,
        homepage_ok=run.homepage_ok,
        summary_json=run.summary_json,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _finding_item(finding: HHealthFinding) -> FindingItem:
    return FindingItem(
        id=finding.id,
        run_id=finding.run_id,
        finding_type=finding.finding_type,
        url=finding.url,
        status_code=finding.status_code,
        response_ms=finding.response_ms,
        detail=finding.detail,
        status=finding.status,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )


@router.get("/runs", response_model=RunsResponse)
def h_runs_list(
    limit: int = Query(default=30, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> RunsResponse:
    del user
    service.reap_stale_runs(db)
    db.commit()
    rows = db.scalars(
        select(HHealthRun)
        .order_by(HHealthRun.created_at.desc(), HHealthRun.id.desc())
        .limit(limit)
    ).all()
    return RunsResponse(runs=[_run_item(row) for row in rows])


@router.post("/runs/trigger", response_model=RunItem)
def h_run_trigger(
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_MANAGE)),
) -> RunItem | JSONResponse:
    del user
    try:
        run = service.trigger_manual_run(db)
    except service.HHealthDispatchError:
        # Return directly so the production-wide >=500 exception sanitizer
        # cannot replace this operator-actionable contract detail.
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": service.N8N_UNREACHABLE_DETAIL},
        )
    db.refresh(run)
    return _run_item(run)


@router.get("/runs/{run_id}", response_model=RunDetail)
def h_run_get(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> RunDetail:
    del user
    run = db.get(HHealthRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="巡检运行不存在。")
    findings = db.scalars(
        select(HHealthFinding)
        .where(HHealthFinding.run_id == run.id)
        .order_by(HHealthFinding.created_at.desc(), HHealthFinding.id.desc())
        .limit(200)
    ).all()
    return RunDetail(
        **_run_item(run).model_dump(),
        findings=[_finding_item(row) for row in findings],
    )


@router.get("/findings", response_model=FindingsResponse)
def h_findings_list(
    status_filter: str = Query(
        default="open",
        alias="status",
        pattern="^(open|acknowledged|resolved)$",
    ),
    finding_type: str | None = Query(
        default=None,
        pattern="^(broken_link|slow_page|sitemap_error|homepage_error)$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> FindingsResponse:
    del user
    query = select(HHealthFinding).where(HHealthFinding.status == status_filter)
    if finding_type:
        query = query.where(HHealthFinding.finding_type == finding_type)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(
        query.order_by(
            HHealthFinding.created_at.desc(), HHealthFinding.id.desc()
        ).limit(limit)
    ).all()
    return FindingsResponse(items=[_finding_item(row) for row in rows], total=total)


@router.patch("/findings/{finding_id}", response_model=FindingItem)
def h_finding_update(
    finding_id: UUID,
    payload: FindingActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_MANAGE)),
) -> FindingItem:
    del user
    try:
        finding = service.transition_finding(
            db,
            finding_id=finding_id,
            action=payload.action,
        )
    except service.HHealthNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.HHealthStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(finding)
    return _finding_item(finding)


@router.post("/ingest", response_model=IngestResponse)
def h_ingest(
    payload: IngestRequest,
    x_h_ingest_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> IngestResponse:
    expected = os.getenv("H_INGEST_TOKEN") or ""
    supplied = x_h_ingest_token or ""
    if not expected or not supplied or not secrets.compare_digest(
        expected.encode("utf-8"), supplied.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="ingest token 无效。")
    try:
        run, deduped = service.ingest_run(
            db,
            run_id=payload.run_id,
            result_status=payload.status,
            error=payload.error,
            summary=payload.summary.model_dump(mode="python"),
            findings=[
                item.model_dump(mode="python", exclude_unset=True)
                for item in payload.findings
            ],
        )
    except service.HHealthNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return IngestResponse(run_id=run.id, deduped=deduped)
