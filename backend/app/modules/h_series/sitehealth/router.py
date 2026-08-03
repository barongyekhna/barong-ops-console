"""FastAPI control-plane and machine-ingest endpoints for H site health."""

from __future__ import annotations

import os
import secrets
from datetime import datetime
import json
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....api.deps import get_current_user
from ....core.roles import is_super_admin_role
from ....db.session import get_db
from ....models.user import User
from ....services.permission_service import resolve_current_user_permission_info
from ....services import wp_bridge
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
    # 本轮**确实访问过**的地址清单，用来自动关掉已经修好的问题。
    #
    # 为什么必须由执行面报上来，而不是后端拿「这次没报 = 修好了」去推断：
    # 一轮巡检可能因为限速、时间预算截断而**没检查到**一部分地址，那些地址上
    # 的老问题这次自然不会出现在 findings 里。靠"没报"推断就会把它们一并
    # 判成已修复——那比不关更糟，因为人会以为没事了。
    checked_urls: list[str] = Field(default_factory=list, max_length=4000)


class IngestResponse(BaseModel):
    run_id: UUID
    deduped: bool


class RedirectRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_path: str = Field(alias="from")
    to: str

    @field_validator("from_path")
    @classmethod
    def validate_from_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("旧路径必须以 / 开头。")
        if len(normalized) > 500:
            raise ValueError("旧路径不能超过 500 个字符。")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("旧路径不能包含控制字符。")
        return normalized

    @field_validator("to")
    @classmethod
    def validate_to(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("/"):
            if normalized.startswith("//") or "\\" in normalized:
                raise ValueError("新目标不能是站外跳转。")
            if any(
                ord(character) < 32 or ord(character) == 127
                for character in normalized
            ):
                raise ValueError("新目标不能包含控制字符。")
            return normalized

        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "barongyekhna.com"
            or parsed.hostname != "barongyekhna.com"
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/")
        ):
            raise ValueError("新目标只能是站内路径或 barongyekhna.com HTTPS 地址。")
        return normalized


class RedirectRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[RedirectRule] = Field(max_length=200)


class RedirectVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("验证路径必须以 / 开头。")
        if len(normalized) > 2048:
            raise ValueError("验证路径过长。")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("验证路径不能包含控制字符。")
        return normalized


def _normalized_redirect_rules(rules: list[RedirectRule]) -> list[dict[str, str]]:
    """Trim and dedupe redirect rows, retaining the last duplicate."""

    by_source: dict[str, str] = {}
    for rule in rules:
        # Moving a duplicate to the end makes response/UI order match the
        # documented "last row wins" behavior as well as its stored value.
        by_source.pop(rule.from_path, None)
        by_source[rule.from_path] = rule.to
    return [
        {"from": source, "to": target}
        for source, target in by_source.items()
    ]


def _redirect_rules_from_option(value: Any) -> tuple[list[dict[str, str]], str | None]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        if parsed in (None, ""):
            parsed = {}
        if not isinstance(parsed, dict):
            raise ValueError("redirect map is not an object")
        candidates = [
            RedirectRule.model_validate({"from": source, "to": target})
            for source, target in parsed.items()
            if isinstance(source, str) and isinstance(target, str)
        ]
        if len(candidates) != len(parsed):
            raise ValueError("redirect map contains non-string rows")
        return _normalized_redirect_rules(candidates), None
    except (TypeError, ValueError, json.JSONDecodeError):
        return [], "WordPress 跳转表 JSON 已损坏，当前以空表显示；保存前请确认。"


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


@router.get("/wp/redirects")
def h_wp_redirects_get(
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    result = wp_bridge.get_option(
        "barong_redirect_map",
        db=db,
        org_id=user.organization_id,
    )
    if not result.get("reachable"):
        return {**result, "rules": []}
    rules, parse_error = _redirect_rules_from_option(result.get("value"))
    response: dict[str, Any] = {"reachable": True, "rules": rules}
    if parse_error:
        response["parse_error"] = parse_error
    return response


@router.put("/wp/redirects")
def h_wp_redirects_put(
    payload: RedirectRulesRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    rules = _normalized_redirect_rules(payload.rules)
    serialized = json.dumps(
        {rule["from"]: rule["to"] for rule in rules},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    result = wp_bridge.set_option(
        "barong_redirect_map",
        serialized,
        db=db,
        org_id=user.organization_id,
    )
    if not result.get("reachable"):
        return {**result, "rules": rules}
    return {"reachable": True, "rules": rules}


@router.post("/wp/redirects/verify")
def h_wp_redirects_verify(
    payload: RedirectVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    return wp_bridge.verify_redirect(
        payload.path,
        db=db,
        org_id=user.organization_id,
    )


@router.get("/wp/sentinel")
def h_wp_sentinel(
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_READ)),
) -> dict[str, Any]:
    return wp_bridge.sentinel_snapshot(db=db, org_id=user.organization_id)


@router.post("/wp/smtp-check")
def h_wp_smtp_check(
    db: Session = Depends(get_db),
    user: User = Depends(_require_h_permission(PERMISSION_MANAGE)),
) -> dict[str, Any]:
    return wp_bridge.smtp_check(db=db, org_id=user.organization_id)


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
            checked_urls=payload.checked_urls,
        )
    except service.HHealthNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return IngestResponse(run_id=run.id, deduped=deduped)
