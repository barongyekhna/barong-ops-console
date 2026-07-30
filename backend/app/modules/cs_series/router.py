"""Public ingress and authenticated management APIs for the CS inbox."""

from __future__ import annotations

import json
import logging
import secrets
from hashlib import sha256
from ipaddress import ip_address
from math import ceil
from typing import Any
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.config import Settings, get_settings
from ...core.permissions import SCOPE_ORGANIZATION
from ...db.session import SessionLocal, get_db
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.permission_decision_engine import PermissionDecisionEngine
from ...services.unified_permission_engine import UnifiedPermissionRequest
from ..notifications.service import create_notification
from .models import (
    CSMessage,
    CSReply,
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    TARGET_ORGANIZATION_NAME,
)
from .reply_service import (
    CSReplyDeliveryError,
    CSReplyTarget,
    send_cs_reply_to_wp,
)
from .schemas import (
    CSChannel,
    CSMessageDetail,
    CSMessageListResponse,
    CSMessageRead,
    CSMessageUpdate,
    CSReplyCreate,
    CSReplyRead,
    CSStatus,
    CSSummaryResponse,
)
from .service import (
    InboundValidationError,
    normalize_inbound,
    plain_text,
    register_shared_inbound_rate_limit,
)

MODULE_KEY = "cs.customer_service"
PERMISSION_READ = "cs.customer_service.read"
PERMISSION_UPDATE = "cs.customer_service.update"
PAGE_SIZE = 25
MAX_INBOUND_BODY_BYTES = 32 * 1024

logger = logging.getLogger(__name__)
public_router = APIRouter(prefix="/cs", tags=["cs-public"])
router = APIRouter(prefix="/cs", tags=["cs-customer-service"])


def _public_response(status_code: int, *, ok: bool) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": ok})


def _expected_inbound_key(settings: Settings) -> str:
    secret = settings.cs_inbound_key
    return secret.get_secret_value() if secret is not None else ""


def _key_is_valid(request: Request, settings: Settings) -> bool:
    expected = _expected_inbound_key(settings)
    supplied = request.headers.get("X-BY-CS-KEY") or ""
    # Hash to fixed-width inputs so even a wrong-length candidate takes the
    # same comparison path. Missing-key requests also execute compare_digest.
    compared = secrets.compare_digest(
        sha256(expected.encode("utf-8")).digest(),
        sha256(supplied.encode("utf-8")).digest(),
    )
    return bool(expected and supplied and compared)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For-Origin")
    candidates = [forwarded.split(",", 1)[0].strip()] if forwarded else []
    if request.client is not None:
        candidates.append(request.client.host.strip())
    for candidate in candidates:
        try:
            return str(ip_address(candidate))
        except ValueError:
            continue
    return "unknown"


async def _read_inbound_json(request: Request) -> Any:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.strip().lower() != "application/json":
        raise InboundValidationError("content type must be JSON")

    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_INBOUND_BODY_BYTES:
                raise InboundValidationError("payload too large")
        except ValueError as exc:
            raise InboundValidationError("invalid content length") from exc

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_INBOUND_BODY_BYTES:
            raise InboundValidationError("payload too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InboundValidationError("invalid JSON") from exc


def _honeypot_filled(raw: Any) -> bool:
    if not isinstance(raw, dict) or "honeypot" not in raw:
        return False
    value = raw.get("honeypot")
    return value is not None and str(value) != ""


def _target_organization(db: Session) -> OrganizationRecord | None:
    with without_org_data_isolation():
        organizations = list(
            db.scalars(
                select(OrganizationRecord)
                .where(
                    OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME,
                    OrganizationRecord.status == "active",
                )
                .order_by(OrganizationRecord.org_id)
                .limit(2)
            )
        )
    if len(organizations) != 1:
        if len(organizations) > 1:
            logger.error("CS inbound target organization name is ambiguous")
        return None
    return organizations[0]


def _notification_route(message: CSMessage) -> str:
    return (
        "/cs/customer-service"
        f"?channel={message.channel}&message={message.id}"
    )


def _emit_inbound_notification(db: Session, message: CSMessage) -> None:
    route = _notification_route(message)
    create_notification(
        db,
        event_type=f"cs.inbound.{message.channel}",
        title="新零售咨询" if message.channel == "retail" else "新批发询盘",
        body=(
            "客服中心收到一条零售咨询，请进入对应分队处理。"
            if message.channel == "retail"
            else "客服中心收到一条批发询盘，请进入对应分队处理。"
        ),
        level="warning" if message.status == "spam" else "info",
        source=MODULE_KEY,
        org_id=message.org_id,
        external_refs={"console_path": route},
        payload={
            "channel": message.channel,
            "message_id": str(message.id),
            "route": route,
        },
    )


def _process_inbound(
    raw: Any,
    client_ip: str,
    user_agent: str | None,
) -> int:
    """Run all blocking database work outside the ASGI event loop."""

    with SessionLocal() as db:
        try:
            rate_allowed = register_shared_inbound_rate_limit(db, client_ip)
            # Persist shared abuse-control buckets before validation and before
            # the message transaction, so rejected requests still count.
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning("CS inbound rate-limit contention")
            return status.HTTP_429_TOO_MANY_REQUESTS
        except SQLAlchemyError:
            db.rollback()
            logger.exception("CS inbound rate limiter unavailable")
            return status.HTTP_503_SERVICE_UNAVAILABLE
        if not rate_allowed:
            return status.HTTP_429_TOO_MANY_REQUESTS

        try:
            payload = normalize_inbound(raw)
        except InboundValidationError:
            return status.HTTP_422_UNPROCESSABLE_ENTITY

        try:
            organization = _target_organization(db)
        except SQLAlchemyError:
            db.rollback()
            logger.exception("CS inbound target organization lookup failed")
            return status.HTTP_503_SERVICE_UNAVAILABLE
        if organization is None:
            logger.error("CS inbound target organization is unavailable")
            db.rollback()
            return status.HTTP_503_SERVICE_UNAVAILABLE

        row = CSMessage(
            org_id=organization.org_id,
            workspace_key=organization.org_id,
            business_context=DEFAULT_BUSINESS_CONTEXT,
            scope_mode=DEFAULT_SCOPE_MODE,
            organization_name=TARGET_ORGANIZATION_NAME,
            channel=payload.channel,
            name=payload.name,
            email=payload.email,
            company=payload.company,
            order_number=payload.order_number,
            message=payload.message,
            source_url=payload.source_url,
            client_ip=client_ip,
            user_agent=user_agent,
            status=payload.status,
        )
        db.add(row)
        try:
            # Persist first so a notification failure cannot roll the customer
            # message back.
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("CS inbound persistence failed")
            return status.HTTP_503_SERVICE_UNAVAILABLE

        message_id = str(row.id)
        # 批发渠道的询盘顺手落进 B2B 线索池（和 P 上架成功后灌批发目录同套路）。
        # 包在 safely 里：B2B 出问题绝不许把客服消息带崩。
        from ..b2b.inbound_bridge import ingest_wholesale_inquiry_safely

        ingest_wholesale_inquiry_safely(db, row)
        try:
            _emit_inbound_notification(db, row)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "CS inbound notification failed message_id=%s",
                message_id,
            )
        return status.HTTP_200_OK


@public_router.post("/inbound")
async def cs_inbound(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if not _key_is_valid(request, settings):
        return _public_response(status.HTTP_401_UNAUTHORIZED, ok=False)

    try:
        raw = await _read_inbound_json(request)
    except InboundValidationError:
        return _public_response(status.HTTP_400_BAD_REQUEST, ok=False)

    # A bot that touches the trap receives the same success contract as a real
    # submitter, without reaching validation, persistence, or notifications.
    if _honeypot_filled(raw):
        return _public_response(status.HTTP_200_OK, ok=True)

    response_status = await to_thread.run_sync(
        _process_inbound,
        raw,
        _client_ip(request),
        (
            (request.headers.get("user-agent") or "").strip()
            or str((raw.get("user_agent") if isinstance(raw, dict) else "") or "").strip()
        )[:300]
        or None,
    )
    return _public_response(
        response_status,
        ok=response_status == status.HTTP_200_OK,
    )


def _require_cs_permission(permission_key: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        workspace_key = _workspace_key(request, user)
        target = _target_organization(db)
        if target is None or target.org_id != workspace_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer-service workspace is unavailable.",
            )
        allowed_keys = {permission_key}
        if permission_key == PERMISSION_READ:
            allowed_keys.add(PERMISSION_UPDATE)
        permission_engine = PermissionDecisionEngine(db, request=request)
        for candidate in allowed_keys:
            decision = permission_engine.decide_permission_key(
                UnifiedPermissionRequest(
                    user_id=user.id,
                    org_id=workspace_key,
                    module_id=MODULE_KEY,
                    action=candidate.rsplit(".", 1)[-1],
                    role=user.role,
                    scope_type=SCOPE_ORGANIZATION,
                    scope_key=workspace_key,
                    permission_key=candidate,
                    source="cs_customer_service_api",
                )
            )
            if decision.allowed:
                return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_key}",
        )

    return dependency


def _workspace_key(request: Request, user: User) -> str:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        org_context = getattr(request.state, "org_context", None)
        org_id = getattr(org_context, "org_id", None)
    if org_id is None:
        org_id = user.organization_id
    normalized = str(org_id or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context is required.",
        )
    return normalized


def _scoped_message(
    db: Session,
    *,
    message_id: UUID,
    workspace_key: str,
    for_update: bool = False,
) -> CSMessage:
    statement = select(CSMessage).where(
        CSMessage.id == message_id,
        CSMessage.org_id == workspace_key,
        CSMessage.workspace_key == workspace_key,
    )
    if for_update:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    return row


def _message_detail(db: Session, message: CSMessage) -> CSMessageDetail:
    replies = list(
        db.scalars(
            select(CSReply)
            .where(CSReply.message_id == message.id)
            .order_by(CSReply.created_at.asc(), CSReply.id.asc())
        )
    )
    base = CSMessageRead.model_validate(message)
    return CSMessageDetail(
        **base.model_dump(),
        replies=[CSReplyRead.model_validate(reply) for reply in replies],
    )


@router.get("/messages", response_model=CSMessageListResponse)
def cs_messages_list(
    request: Request,
    channel: CSChannel = Query(...),
    status_filter: CSStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(_require_cs_permission(PERMISSION_READ)),
) -> CSMessageListResponse:
    workspace_key = _workspace_key(request, user)
    filters = [
        CSMessage.org_id == workspace_key,
        CSMessage.workspace_key == workspace_key,
        CSMessage.channel == channel,
    ]
    if status_filter is not None:
        filters.append(CSMessage.status == status_filter)
    total = int(
        db.scalar(select(func.count()).select_from(CSMessage).where(*filters)) or 0
    )
    rows = list(
        db.scalars(
            select(CSMessage)
            .where(*filters)
            .order_by(CSMessage.created_at.desc(), CSMessage.id.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )
    return CSMessageListResponse(
        items=[CSMessageRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        pages=max(1, ceil(total / PAGE_SIZE)),
    )


@router.get("/summary", response_model=CSSummaryResponse)
def cs_summary(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cs_permission(PERMISSION_READ)),
) -> CSSummaryResponse:
    workspace_key = _workspace_key(request, user)
    rows = db.execute(
        select(CSMessage.channel, func.count())
        .where(
            CSMessage.org_id == workspace_key,
            CSMessage.workspace_key == workspace_key,
            CSMessage.status == "new",
        )
        .group_by(CSMessage.channel)
    ).all()
    counts = {str(channel): int(count) for channel, count in rows}
    return CSSummaryResponse(
        retail={"new": counts.get("retail", 0)},
        wholesale={"new": counts.get("wholesale", 0)},
    )


@router.get("/messages/{message_id}", response_model=CSMessageDetail)
def cs_message_get(
    message_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cs_permission(PERMISSION_READ)),
) -> CSMessageDetail:
    row = _scoped_message(
        db,
        message_id=message_id,
        workspace_key=_workspace_key(request, user),
    )
    return _message_detail(db, row)


@router.post("/messages/{message_id}/reply", response_model=CSReplyRead)
def cs_message_reply(
    message_id: UUID,
    payload: CSReplyCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cs_permission(PERMISSION_UPDATE)),
    settings: Settings = Depends(get_settings),
) -> CSReplyRead:
    workspace_key = _workspace_key(request, user)
    message = _scoped_message(
        db,
        message_id=message_id,
        workspace_key=workspace_key,
    )
    body = plain_text(payload.body, multiline=True)
    if not body or len(body) > 10000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reply body must contain between 1 and 10000 characters.",
        )

    # Snapshot everything needed by the relay, then end the read transaction;
    # the network call may take 15 seconds and must not hold a DB connection.
    target = CSReplyTarget(
        email=message.email,
        name=message.name,
        channel=message.channel,
    )
    sent_by = int(user.id)
    db.rollback()

    provider_note: str | None = None
    try:
        send_cs_reply_to_wp(
            settings=settings,
            message=target,
            body=body,
        )
    except CSReplyDeliveryError as exc:
        provider_note = exc.provider_note
    except Exception:
        logger.exception("Unexpected CS reply relay failure message_id=%s", message_id)
        provider_note = "WordPress reply relay request failed."

    if provider_note is not None:
        failed = CSReply(
            message_id=message_id,
            body=body,
            sent_by=sent_by,
            delivery_status="failed",
            provider_note=provider_note[:300],
        )
        db.add(failed)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "cs_reply_delivery_failed",
                "message": provider_note,
            },
        )

    # Re-scope after the external call; sent reply persistence and the automatic
    # new -> in_progress transition form one atomic local transaction.
    current = _scoped_message(
        db,
        message_id=message_id,
        workspace_key=workspace_key,
        for_update=True,
    )
    reply = CSReply(
        message_id=message_id,
        body=body,
        sent_by=sent_by,
        delivery_status="sent",
    )
    db.add(reply)
    if current.status == "new":
        current.status = "in_progress"
    db.commit()
    return CSReplyRead.model_validate(reply)


@router.patch("/messages/{message_id}", response_model=CSMessageRead)
def cs_message_update(
    message_id: UUID,
    payload: CSMessageUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_cs_permission(PERMISSION_UPDATE)),
) -> CSMessageRead:
    if not payload.model_fields_set or (
        payload.model_fields_set == {"status"} and payload.status is None
    ):
        raise HTTPException(status_code=422, detail="No update fields supplied.")
    row = _scoped_message(
        db,
        message_id=message_id,
        workspace_key=_workspace_key(request, user),
    )
    if "status" in payload.model_fields_set and payload.status is not None:
        row.status = payload.status
    if "internal_note" in payload.model_fields_set:
        row.internal_note = (
            plain_text(payload.internal_note, multiline=True)
            if payload.internal_note is not None
            else None
        )
    db.flush()
    db.commit()
    db.refresh(row)
    return CSMessageRead.model_validate(row)


__all__ = [
    "MODULE_KEY",
    "PAGE_SIZE",
    "PERMISSION_READ",
    "PERMISSION_UPDATE",
    "public_router",
    "router",
]
