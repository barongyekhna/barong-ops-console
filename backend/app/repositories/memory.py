from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.context import ContextPacket
from ..models.memory import MemoryEvent, MemorySummary
from ..schemas.memory import ContextPacketCreate, MemoryEventCreate


def list_memory_events(
    db: Session, *, limit: int, offset: int
) -> list[MemoryEvent]:
    return list(
        db.scalars(
            select(MemoryEvent)
            .order_by(MemoryEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_memory_event(
    db: Session, memory_event_id: str
) -> MemoryEvent | None:
    return db.scalar(
        select(MemoryEvent).where(
            MemoryEvent.memory_event_id == memory_event_id
        )
    )


def create_memory_event(
    db: Session,
    *,
    payload: MemoryEventCreate,
    created_by_id: str,
    created_by_type: str = "user",
) -> MemoryEvent:
    event = MemoryEvent(
        **payload.model_dump(),
        created_by_type=created_by_type,
        created_by_id=created_by_id,
    )
    db.add(event)
    return event


def list_context_packets(
    db: Session, *, limit: int, offset: int
) -> list[ContextPacket]:
    return list(
        db.scalars(
            select(ContextPacket)
            .order_by(ContextPacket.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_context_packet(
    db: Session, context_packet_id: str
) -> ContextPacket | None:
    return db.scalar(
        select(ContextPacket).where(
            ContextPacket.context_packet_id == context_packet_id
        )
    )


def create_context_packet(
    db: Session, payload: ContextPacketCreate
) -> ContextPacket:
    packet = ContextPacket(
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
    return packet


def list_memory_summaries(
    db: Session, *, limit: int, offset: int
) -> list[MemorySummary]:
    return list(
        db.scalars(
            select(MemorySummary)
            .order_by(MemorySummary.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def get_memory_summary(
    db: Session, summary_id: str
) -> MemorySummary | None:
    return db.scalar(
        select(MemorySummary).where(
            MemorySummary.memory_summary_id == summary_id
        )
    )
