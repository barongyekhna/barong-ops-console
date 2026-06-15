from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.user import User
from ...repositories.jobs import get_job
from ...repositories.memory import (
    create_context_packet,
    create_memory_event,
    get_context_packet,
    get_memory_event,
    get_memory_summary,
    list_context_packets,
    list_memory_events,
    list_memory_summaries,
)
from ...repositories.registry import get_agent, get_module
from ...schemas.common import ListResponse
from ...schemas.memory import (
    ContextPacketCreate,
    ContextPacketResponse,
    MemoryEventCreate,
    MemoryEventResponse,
    MemorySummaryResponse,
)
from ...services.foundation_service import (
    commit_foundation_write,
    conflict,
    invalid_reference,
    not_found,
)
from ..deps import get_audit_context, require_rbac

router = APIRouter(tags=["memory"])


@router.get(
    "/memory-events",
    response_model=ListResponse[MemoryEventResponse],
)
def memory_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ListResponse[MemoryEventResponse]:
    del user
    items = list_memory_events(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/memory-events/{memory_event_id}", response_model=MemoryEventResponse)
def memory_event_detail(
    memory_event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> MemoryEventResponse:
    del user
    event = get_memory_event(db, memory_event_id)
    if event is None:
        raise not_found("Memory event", memory_event_id)
    return MemoryEventResponse.model_validate(event)


@router.post(
    "/memory-events",
    response_model=MemoryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def memory_event_create(
    payload: MemoryEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> MemoryEventResponse:
    if get_memory_event(db, payload.memory_event_id) is not None:
        raise conflict("Memory event", payload.memory_event_id)
    if payload.job_id and get_job(db, payload.job_id) is None:
        raise invalid_reference("Memory event job_id is not registered.")
    event = create_memory_event(
        db,
        payload=payload,
        created_by_id=str(user.id),
    )
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="memory_event.create_demo",
        target_type="memory_event",
        target_id=payload.memory_event_id,
        job_id=payload.job_id,
        details={"model_called": False},
    )
    db.refresh(event)
    return MemoryEventResponse.model_validate(event)


@router.get(
    "/context-packets",
    response_model=ListResponse[ContextPacketResponse],
)
def context_packets(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ListResponse[ContextPacketResponse]:
    del user
    items = list_context_packets(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get(
    "/context-packets/{context_packet_id}",
    response_model=ContextPacketResponse,
)
def context_packet_detail(
    context_packet_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ContextPacketResponse:
    del user
    packet = get_context_packet(db, context_packet_id)
    if packet is None:
        raise not_found("Context packet", context_packet_id)
    return ContextPacketResponse.model_validate(packet)


@router.post(
    "/context-packets",
    response_model=ContextPacketResponse,
    status_code=status.HTTP_201_CREATED,
)
def context_packet_create(
    payload: ContextPacketCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ContextPacketResponse:
    if get_context_packet(db, payload.context_packet_id) is not None:
        raise conflict("Context packet", payload.context_packet_id)
    if get_job(db, payload.source_job_id) is None:
        raise invalid_reference("Context packet source_job_id is not registered.")
    if get_module(db, payload.source_module_key) is None:
        raise invalid_reference(
            "Context packet source_module_key is not registered."
        )
    if (
        payload.target_module_key
        and get_module(db, payload.target_module_key) is None
    ):
        raise invalid_reference(
            "Context packet target_module_key is not registered."
        )
    if payload.target_agent_key and get_agent(
        db, payload.target_agent_key
    ) is None:
        raise invalid_reference(
            "Context packet target_agent_key is not registered."
        )
    if payload.expires_at <= datetime.now(timezone.utc):
        raise invalid_reference("Context packet expires_at must be in the future.")

    packet = create_context_packet(db, payload)
    commit_foundation_write(
        db,
        user=user,
        audit=get_audit_context(request),
        action="context_packet.create_demo",
        target_type="context_packet",
        target_id=payload.context_packet_id,
        job_id=payload.source_job_id,
        details={"model_called": False},
    )
    db.refresh(packet)
    return ContextPacketResponse.model_validate(packet)


@router.get(
    "/memory-summaries",
    response_model=ListResponse[MemorySummaryResponse],
)
def memory_summaries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> ListResponse[MemorySummaryResponse]:
    del user
    items = list_memory_summaries(db, limit=limit, offset=offset)
    return ListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get(
    "/memory-summaries/{summary_id}",
    response_model=MemorySummaryResponse,
)
def memory_summary_detail(
    summary_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_rbac("AUDIT", "admin")),
) -> MemorySummaryResponse:
    del user
    summary = get_memory_summary(db, summary_id)
    if summary is None:
        raise not_found("Memory summary", summary_id)
    return MemorySummaryResponse.model_validate(summary)
