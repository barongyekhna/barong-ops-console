from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.context import ContextPacket
from ..models.memory import MemoryEvent, MemorySummary
from ..schemas.memory import ContextPacketCreate, MemoryEventCreate
from ..services.event_collector import record_product_knowledge_event
from .tenant import current_tenant_org_id, tenant_org_id_for_create


def list_memory_events(
    db: Session, *, limit: int, offset: int
) -> list[MemoryEvent]:
    org_id = current_tenant_org_id()
    events = list(
        db.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.org_id == org_id)
            .order_by(MemoryEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    record_product_knowledge_event(
        action="read",
        payload={"operation": "list_memory_events", "count": len(events)},
    )
    return events


def get_memory_event(
    db: Session, memory_event_id: str
) -> MemoryEvent | None:
    org_id = current_tenant_org_id()
    event = db.scalar(
        select(MemoryEvent).where(
            MemoryEvent.memory_event_id == memory_event_id,
            MemoryEvent.org_id == org_id,
        )
    )
    record_product_knowledge_event(
        action="read",
        status="success" if event is not None else "failed",
        payload={
            "operation": "get_memory_event",
            "memory_event_id": memory_event_id,
        },
    )
    return event


def create_memory_event(
    db: Session,
    *,
    payload: MemoryEventCreate,
    created_by_id: str,
    created_by_type: str = "user",
) -> MemoryEvent:
    event = MemoryEvent(
        org_id=tenant_org_id_for_create(),
        **payload.model_dump(),
        created_by_type=created_by_type,
        created_by_id=created_by_id,
    )
    db.add(event)
    record_product_knowledge_event(
        action="write",
        payload={
            "operation": "create_memory_event",
            "memory_event_id": payload.memory_event_id,
            "subject_type": payload.subject_type,
            "subject_id": payload.subject_id,
            "job_id": payload.job_id,
        },
    )
    return event


def list_context_packets(
    db: Session, *, limit: int, offset: int
) -> list[ContextPacket]:
    org_id = current_tenant_org_id()
    packets = list(
        db.scalars(
            select(ContextPacket)
            .where(ContextPacket.org_id == org_id)
            .order_by(ContextPacket.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    record_product_knowledge_event(
        action="read",
        payload={"operation": "list_context_packets", "count": len(packets)},
    )
    return packets


def get_context_packet(
    db: Session, context_packet_id: str
) -> ContextPacket | None:
    org_id = current_tenant_org_id()
    packet = db.scalar(
        select(ContextPacket).where(
            ContextPacket.context_packet_id == context_packet_id,
            ContextPacket.org_id == org_id,
        )
    )
    record_product_knowledge_event(
        action="read",
        status="success" if packet is not None else "failed",
        payload={
            "operation": "get_context_packet",
            "context_packet_id": context_packet_id,
        },
    )
    return packet


def create_context_packet(
    db: Session, payload: ContextPacketCreate
) -> ContextPacket:
    packet = ContextPacket(
        org_id=tenant_org_id_for_create(),
        context_packet_id=payload.context_packet_id,
        source_job_id=payload.source_job_id,
        source_module_id=payload.source_module_key,
        target_module_id=payload.target_module_key,
        target_agent_id=payload.target_agent_key,
        schema_version=payload.schema_version,
        payload=payload.payload,
        artifact_refs=payload.artifact_refs,
        access_scope=payload.access_scope,
        expires_at=payload.expires_at,
    )
    db.add(packet)
    record_product_knowledge_event(
        action="write",
        payload={
            "operation": "create_context_packet",
            "context_packet_id": payload.context_packet_id,
            "source_job_id": payload.source_job_id,
            "source_module_key": payload.source_module_key,
            "target_module_key": payload.target_module_key,
        },
    )
    return packet


def list_memory_summaries(
    db: Session, *, limit: int, offset: int
) -> list[MemorySummary]:
    org_id = current_tenant_org_id()
    summaries = list(
        db.scalars(
            select(MemorySummary)
            .where(MemorySummary.org_id == org_id)
            .order_by(MemorySummary.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    record_product_knowledge_event(
        action="read",
        payload={"operation": "list_memory_summaries", "count": len(summaries)},
    )
    return summaries


def get_memory_summary(
    db: Session, summary_id: str
) -> MemorySummary | None:
    org_id = current_tenant_org_id()
    summary = db.scalar(
        select(MemorySummary).where(
            MemorySummary.memory_summary_id == summary_id,
            MemorySummary.org_id == org_id,
        )
    )
    record_product_knowledge_event(
        action="read",
        status="success" if summary is not None else "failed",
        payload={"operation": "get_memory_summary", "summary_id": summary_id},
    )
    return summary
