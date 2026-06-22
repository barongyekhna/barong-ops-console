from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.error import SystemError
from ..models.user import User
from ..repositories.artifacts import create_artifact
from ..repositories.foundation_demo import (
    FOUNDATION_DEMO_JOB_TYPE,
    FOUNDATION_DEMO_MODULE_KEY,
    create_foundation_demo_event,
    get_foundation_demo_artifact,
    get_foundation_demo_memory_event,
    get_foundation_demo_review,
    get_latest_foundation_demo_job,
    list_foundation_demo_events,
    list_foundation_demo_operation_logs,
)
from ..repositories.jobs import create_job
from ..repositories.memory import create_memory_event
from ..repositories.operation_logs import create_operation_log
from ..repositories.registry import (
    create_agent,
    create_module,
    create_workflow,
    get_agent,
    get_module,
    get_workflow,
)
from ..repositories.reviews import create_review
from ..schemas.artifacts import ArtifactCreate, ArtifactResponse
from ..schemas.foundation_demo import (
    FoundationDemoArtifactResponse,
    FoundationDemoJobResponse,
    FoundationDemoMemoryEventResponse,
    FoundationDemoOperationLogSummary,
    FoundationDemoWorkflowResponse,
)
from ..schemas.jobs import JobCreate, JobEventResponse, JobResponse
from ..schemas.memory import MemoryEventCreate, MemoryEventResponse
from ..schemas.registry import (
    AgentCreate,
    AgentResponse,
    ModuleCreate,
    ModuleResponse,
    WorkflowCreate,
    WorkflowResponse,
)
from ..schemas.reviews import ReviewCreate, ReviewResponse
from .auth_service import AuditContext

FOUNDATION_DEMO_AGENT_KEY = "foundation_demo_agent"
FOUNDATION_DEMO_WORKFLOW_KEY = "foundation_demo_workflow"
FOUNDATION_DEMO_TRIGGER_TYPE = "internal_demo"


class FoundationDemoRunError(RuntimeError):
    pass


def _new_id(kind: str) -> str:
    return f"foundation_demo_{kind}_{uuid4().hex}"


def _module_payload() -> ModuleCreate:
    return ModuleCreate(
        module_key=FOUNDATION_DEMO_MODULE_KEY,
        name="Foundation Demo Module",
        responsibilities=["Exercise the foundation data flow safely."],
        non_responsibilities=[
            "Execute real business work.",
            "Call external services.",
        ],
        risk_level="demo",
        status="demo",
        artifact_types=["demo_report"],
        review_types=["foundation_demo_review"],
        rollback_policy={"mode": "transaction_rollback"},
    )


def _agent_payload() -> AgentCreate:
    return AgentCreate(
        agent_key=FOUNDATION_DEMO_AGENT_KEY,
        name="Foundation Demo Agent",
        responsibilities=["Record simulated foundation steps."],
        non_responsibilities=[
            "Run real automations.",
            "Call models or external services.",
        ],
        risk_level="demo",
        status="demo",
        allowed_module_keys=[FOUNDATION_DEMO_MODULE_KEY],
        allowed_workflow_keys=[FOUNDATION_DEMO_WORKFLOW_KEY],
    )


def _workflow_payload() -> WorkflowCreate:
    return WorkflowCreate(
        workflow_key=FOUNDATION_DEMO_WORKFLOW_KEY,
        name="Foundation Demo Workflow",
        responsibilities=["Describe the internal demo sequence."],
        non_responsibilities=["Trigger a workflow engine or network call."],
        risk_level="demo",
        status="demo",
        engine=FOUNDATION_DEMO_TRIGGER_TYPE,
        endpoint_ref="demo://internal/foundation",
        callback_contract={
            "trigger_type": FOUNDATION_DEMO_TRIGGER_TYPE,
            "external_http": False,
            "downstream_triggered": False,
        },
        retry_policy={"enabled": False},
    )


def _serialize_workflow(workflow: object) -> FoundationDemoWorkflowResponse:
    payload = WorkflowResponse.model_validate(workflow).model_dump()
    return FoundationDemoWorkflowResponse(
        **payload,
        trigger_type=FOUNDATION_DEMO_TRIGGER_TYPE,
    )


def _serialize_job(job: object) -> FoundationDemoJobResponse:
    payload = JobResponse.model_validate(job).model_dump()
    payload["org_id"] = getattr(job, "org_id")
    return FoundationDemoJobResponse(
        **payload,
        job_type=FOUNDATION_DEMO_JOB_TYPE,
    )


def _serialize_artifact(
    artifact: object,
) -> FoundationDemoArtifactResponse:
    payload = ArtifactResponse.model_validate(artifact).model_dump()
    payload["org_id"] = getattr(artifact, "org_id")
    return FoundationDemoArtifactResponse(
        **payload,
        title=payload["name"],
    )


def _serialize_memory_event(
    memory_event: object,
) -> FoundationDemoMemoryEventResponse:
    payload = MemoryEventResponse.model_validate(memory_event).model_dump()
    payload["org_id"] = getattr(memory_event, "org_id")
    summary = payload["payload"].get("summary", "Foundation demo event.")
    return FoundationDemoMemoryEventResponse(
        **payload,
        summary=str(summary),
    )


def _serialize_operation_log(
    operation_log: object,
) -> FoundationDemoOperationLogSummary:
    return FoundationDemoOperationLogSummary.model_validate(
        operation_log,
        from_attributes=True,
    )


def _snapshot(
    db: Session,
    *,
    job: object,
) -> dict[str, Any]:
    job_id = str(getattr(job, "job_id"))
    events = list_foundation_demo_events(db, job_id)
    artifact = get_foundation_demo_artifact(db, job_id)
    review = get_foundation_demo_review(db, job_id)
    memory_event = get_foundation_demo_memory_event(db, job_id)
    operation_logs = list_foundation_demo_operation_logs(db, job_id)
    return {
        "job": _serialize_job(job),
        "events_count": len(events),
        "artifact": (
            _serialize_artifact(artifact) if artifact is not None else None
        ),
        "review": (
            ReviewResponse.model_validate(review)
            if review is not None
            else None
        ),
        "memory_event": (
            _serialize_memory_event(memory_event)
            if memory_event is not None
            else None
        ),
        "operation_log_count": len(operation_logs),
    }


def _record_failed_run(
    db: Session,
    *,
    actor_id: str,
    audit: AuditContext,
    run_id: str,
    exception_type: str,
    exception_message: str,
) -> None:
    error_id = _new_id("error")
    db.add(
        SystemError(
            error_id=error_id,
            error_code="FOUNDATION_DEMO_RUN_FAILED",
            severity="error_demo",
            status="open_demo",
            message=(
                "Foundation demo transaction failed and was rolled back."
            ),
            details={
                "run_id": run_id,
                "exception_type": exception_type,
                "exception_message": exception_message[:500],
                "real_business_effect": False,
            },
            correlation_id=run_id,
        )
    )
    create_operation_log(
        db,
        actor_type="user",
        actor_id=actor_id,
        action="foundation_demo.run",
        target_type="foundation_demo",
        target_id=run_id,
        result="failure",
        error_code="FOUNDATION_DEMO_RUN_FAILED",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "scope": "foundation_demo",
            "transaction_rolled_back": True,
            "external_http_called": False,
        },
    )
    db.commit()


def run_foundation_demo(
    db: Session,
    *,
    user: User,
    audit: AuditContext,
) -> dict[str, Any]:
    actor_id = str(user.id)
    run_id = _new_id("run")
    operation_logs = []

    def audit_write(
        *,
        action: str,
        target_type: str,
        target_id: str,
        job_id: str,
        details: dict[str, Any],
    ) -> None:
        operation_logs.append(
            create_operation_log(
                db,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                job_id=job_id,
                result="success",
                request_id=audit.request_id,
                ip_address=audit.ip_address,
                user_agent=audit.user_agent,
                details={
                    "scope": "foundation_demo",
                    "run_id": run_id,
                    **details,
                },
            )
        )

    try:
        created_registry: list[tuple[str, str, str, dict[str, Any]]] = []

        module = get_module(db, FOUNDATION_DEMO_MODULE_KEY)
        if module is None:
            module = create_module(db, _module_payload())
            created_registry.append(
                (
                    "foundation_demo.module_created",
                    "module",
                    FOUNDATION_DEMO_MODULE_KEY,
                    {"status": "demo"},
                )
            )

        agent = get_agent(db, FOUNDATION_DEMO_AGENT_KEY)
        if agent is None:
            agent = create_agent(db, _agent_payload())
            created_registry.append(
                (
                    "foundation_demo.agent_created",
                    "agent",
                    FOUNDATION_DEMO_AGENT_KEY,
                    {"status": "demo"},
                )
            )

        workflow = get_workflow(db, FOUNDATION_DEMO_WORKFLOW_KEY)
        if workflow is None:
            workflow = create_workflow(db, _workflow_payload())
            created_registry.append(
                (
                    "foundation_demo.workflow_created",
                    "workflow",
                    FOUNDATION_DEMO_WORKFLOW_KEY,
                    {
                        "trigger_type": FOUNDATION_DEMO_TRIGGER_TYPE,
                        "external_http_called": False,
                    },
                )
            )

        db.flush()

        job_id = _new_id("job")
        job = create_job(
            db,
            payload=JobCreate(
                job_id=job_id,
                module_key=FOUNDATION_DEMO_MODULE_KEY,
                agent_key=FOUNDATION_DEMO_AGENT_KEY,
                workflow_key=FOUNDATION_DEMO_WORKFLOW_KEY,
                status="pending",
                risk_level="demo",
                input_payload={
                    "job_type": FOUNDATION_DEMO_JOB_TYPE,
                    "demo_only": True,
                    "external_calls": False,
                    "real_business_task": False,
                },
                correlation_id=run_id,
            ),
            requested_by_user_id=user.id,
        )
        db.flush()

        for action, target_type, target_id, details in created_registry:
            audit_write(
                action=action,
                target_type=target_type,
                target_id=target_id,
                job_id=job_id,
                details=details,
            )

        audit_write(
            action="foundation_demo.job_created",
            target_type="job",
            target_id=job_id,
            job_id=job_id,
            details={"status": "pending", "job_type": FOUNDATION_DEMO_JOB_TYPE},
        )

        events = []

        def append_event(
            event_type: str,
            *,
            actor_type: str,
            event_actor_id: str,
            to_status: str | None = None,
            details: dict[str, object] | None = None,
        ) -> None:
            event = create_foundation_demo_event(
                db,
                job=job,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=event_actor_id,
                to_status=to_status,
                details=details,
            )
            events.append(event)
            audit_write(
                action=f"foundation_demo.event_{event_type}",
                target_type="job_event",
                target_id=f"{job_id}:{event_type}",
                job_id=job_id,
                details={
                    "event_type": event_type,
                    "to_status": to_status,
                },
            )

        append_event(
            "created",
            actor_type="user",
            event_actor_id=actor_id,
            to_status="pending",
            details={"demo_only": True},
        )
        job.started_at = datetime.now(timezone.utc)
        append_event(
            "running",
            actor_type="demo_agent",
            event_actor_id=FOUNDATION_DEMO_AGENT_KEY,
            to_status="running",
            details={
                "simulated": True,
                "external_http_called": False,
            },
        )

        artifact_id = _new_id("artifact")
        artifact = create_artifact(
            db,
            ArtifactCreate(
                artifact_id=artifact_id,
                job_id=job_id,
                module_key=FOUNDATION_DEMO_MODULE_KEY,
                artifact_type="demo_report",
                name="Foundation Demo Report",
                storage_provider="demo_metadata",
                storage_ref=f"demo/internal/foundation/{artifact_id}",
                status="registered_demo",
                metadata={
                    "demo_only": True,
                    "file_uploaded": False,
                    "external_storage": False,
                },
            ),
        )
        audit_write(
            action="foundation_demo.artifact_created",
            target_type="artifact",
            target_id=artifact_id,
            job_id=job_id,
            details={
                "artifact_type": "demo_report",
                "file_uploaded": False,
            },
        )
        append_event(
            "artifact_created",
            actor_type="demo_agent",
            event_actor_id=FOUNDATION_DEMO_AGENT_KEY,
            details={"artifact_id": artifact_id},
        )

        review_id = _new_id("review")
        review = create_review(
            db,
            payload=ReviewCreate(
                review_id=review_id,
                job_id=job_id,
                artifact_id=artifact_id,
                review_type="foundation_demo_review",
                risk_level="demo",
                status="pending_demo",
            ),
            requested_by=user.id,
        )
        audit_write(
            action="foundation_demo.review_created",
            target_type="review",
            target_id=review_id,
            job_id=job_id,
            details={
                "status": "pending_demo",
                "downstream_triggered": False,
            },
        )
        append_event(
            "review_requested",
            actor_type="demo_agent",
            event_actor_id=FOUNDATION_DEMO_AGENT_KEY,
            to_status="waiting_review",
            details={
                "review_id": review_id,
                "downstream_triggered": False,
            },
        )

        memory_event_id = _new_id("memory")
        memory_event = create_memory_event(
            db,
            payload=MemoryEventCreate(
                memory_event_id=memory_event_id,
                event_type="foundation_demo_completed",
                subject_type="job",
                subject_id=job_id,
                job_id=job_id,
                payload={
                    "summary": (
                        "Foundation demo exercise recorded; no real business "
                        "task or external service was invoked."
                    ),
                    "demo_only": True,
                    "model_called": False,
                },
                importance="normal_demo",
            ),
            created_by_id=actor_id,
        )
        audit_write(
            action="foundation_demo.memory_event_created",
            target_type="memory_event",
            target_id=memory_event_id,
            job_id=job_id,
            details={"model_called": False},
        )
        append_event(
            "memory_event_created",
            actor_type="demo_agent",
            event_actor_id=FOUNDATION_DEMO_AGENT_KEY,
            details={"memory_event_id": memory_event_id},
        )

        job.finished_at = datetime.now(timezone.utc)
        append_event(
            "completed_demo",
            actor_type="demo_agent",
            event_actor_id=FOUNDATION_DEMO_AGENT_KEY,
            to_status="completed_demo",
            details={
                "demo_only": True,
                "real_business_completion": False,
            },
        )
        audit_write(
            action="foundation_demo.run_completed",
            target_type="foundation_demo",
            target_id=run_id,
            job_id=job_id,
            details={
                "status": "completed_demo",
                "workflow_triggered": False,
                "external_http_called": False,
            },
        )

        db.flush()
        result = {
            "module": ModuleResponse.model_validate(module),
            "agent": AgentResponse.model_validate(agent),
            "workflow": _serialize_workflow(workflow),
            "job": _serialize_job(job),
            "job_events": [
                JobEventResponse.model_validate(event) for event in events
            ],
            "events_count": len(events),
            "artifact": _serialize_artifact(artifact),
            "review": ReviewResponse.model_validate(review),
            "memory_event": _serialize_memory_event(memory_event),
            "operation_log_count": len(operation_logs),
            "operation_logs": [
                _serialize_operation_log(item) for item in operation_logs
            ],
        }
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        try:
            _record_failed_run(
                db,
                actor_id=actor_id,
                audit=audit,
                run_id=run_id,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
        except Exception:
            db.rollback()
        raise FoundationDemoRunError(
            "Foundation demo run failed safely."
        ) from None


def get_latest_foundation_demo(db: Session) -> dict[str, Any] | None:
    job = get_latest_foundation_demo_job(db)
    if job is None:
        return None
    return _snapshot(db, job=job)
