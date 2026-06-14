from datetime import datetime, timezone
from hmac import compare_digest
from typing import Any
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.job import AutomationJob
from ..models.user import User
from ..repositories.artifacts import create_artifact
from ..repositories.jobs import create_job, get_job
from ..repositories.memory import create_memory_event
from ..repositories.n8n_test import (
    N8N_TEST_AGENT_KEY,
    N8N_TEST_MODULE_KEY,
    N8N_TEST_RUN_TYPE,
    N8N_TEST_WORKFLOW_KEY,
    create_n8n_test_event,
    get_latest_n8n_test_job,
    get_n8n_test_artifact,
    get_n8n_test_error,
    get_n8n_test_memory_event,
    get_n8n_test_review,
    list_n8n_test_events,
    list_n8n_test_operation_logs,
)
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
from ..schemas.errors import SystemErrorResponse
from ..schemas.jobs import JobEventResponse, JobCreate, JobResponse
from ..schemas.memory import MemoryEventCreate, MemoryEventResponse
from ..schemas.n8n_test import (
    N8nTestArtifactResponse,
    N8nTestCallbackRequest,
    N8nTestJobResponse,
    N8nTestMemoryEventResponse,
)
from ..schemas.registry import AgentCreate, ModuleCreate, WorkflowCreate
from ..schemas.reviews import ReviewCreate, ReviewResponse
from .auth_service import AuditContext
from .n8n_test_http_client import build_n8n_test_mock_response

ALLOWED_TERMINAL_STATUSES = {"completed_demo", "failed"}
CALLBACK_ACTOR_ID = "n8n_test_callback_guard"
MOCK_DISPATCH_ACTOR_ID = "c11b_mock_dispatcher"


class N8nTestCallbackAuthenticationError(RuntimeError):
    pass


class N8nTestCallbackJobError(RuntimeError):
    pass


def _new_id(kind: str) -> str:
    return f"demo_n8n_test_{kind}_{uuid4().hex}"


def _secret_value(value: SecretStr | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _module_payload() -> ModuleCreate:
    return ModuleCreate(
        module_key=N8N_TEST_MODULE_KEY,
        name="n8n Test Bridge Module",
        responsibilities=["Exercise Console n8n mock bridge state."],
        non_responsibilities=[
            "Run production workflows.",
            "Process real product or commerce data.",
        ],
        risk_level="demo",
        status="demo",
        artifact_types=["n8n_test_mock_report"],
        review_types=["n8n_test_mock_review"],
        error_codes=["N8N_TEST_EXTERNAL_EXECUTION_BLOCKED"],
        rollback_policy={"mode": "mock_only_no_external_rollback"},
    )


def _agent_payload() -> AgentCreate:
    return AgentCreate(
        agent_key=N8N_TEST_AGENT_KEY,
        name="n8n Test Agent",
        responsibilities=["Record mock dispatch and blocked callback events."],
        non_responsibilities=["Run real business automations."],
        risk_level="demo",
        status="demo",
        allowed_module_keys=[N8N_TEST_MODULE_KEY],
        allowed_workflow_keys=[N8N_TEST_WORKFLOW_KEY],
    )


def _workflow_payload(timeout_seconds: int) -> WorkflowCreate:
    return WorkflowCreate(
        workflow_key=N8N_TEST_WORKFLOW_KEY,
        name="n8n Test Mock Workflow",
        responsibilities=["Describe the mock-only test bridge contract."],
        non_responsibilities=[
            "Store a network URL, callback credential, or webhook endpoint."
        ],
        risk_level="demo",
        status="demo",
        engine="n8n_test_mock",
        endpoint_ref="demo://n8n-test/mock-only",
        callback_contract={
            "test_mode": True,
            "mock_only": True,
            "callback_connected": False,
            "external_webhook_triggered": False,
        },
        timeout_seconds=timeout_seconds,
        retry_policy={"enabled": False},
    )


def _serialize_job(job: AutomationJob) -> N8nTestJobResponse:
    return N8nTestJobResponse(
        **JobResponse.model_validate(job).model_dump(),
        run_type=N8N_TEST_RUN_TYPE,
    )


def _serialize_artifact(
    artifact: object,
) -> N8nTestArtifactResponse:
    payload = ArtifactResponse.model_validate(artifact).model_dump()
    return N8nTestArtifactResponse(**payload, title=payload["name"])


def _serialize_memory_event(
    memory_event: object,
) -> N8nTestMemoryEventResponse:
    payload = MemoryEventResponse.model_validate(memory_event).model_dump()
    summary = str(payload["payload"].get("summary", "n8n test event."))
    return N8nTestMemoryEventResponse(**payload, summary=summary)


def _snapshot(db: Session, *, job: AutomationJob) -> dict[str, Any]:
    events = list_n8n_test_events(db, job.job_id)
    artifact = get_n8n_test_artifact(db, job.job_id)
    review = get_n8n_test_review(db, job.job_id)
    memory_event = get_n8n_test_memory_event(db, job.job_id)
    error = get_n8n_test_error(db, job.job_id)
    operation_logs = list_n8n_test_operation_logs(db, job.job_id)
    return {
        "test_mode": True,
        "job": _serialize_job(job),
        "latest_event": (
            JobEventResponse.model_validate(events[-1]) if events else None
        ),
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
        "error": (
            SystemErrorResponse.model_validate(error)
            if error is not None
            else None
        ),
        "operation_log_count": len(operation_logs),
    }


def _audit(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
    audit: AuditContext,
    job_id: str | None = None,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        job_id=job_id,
        result=result,
        error_code=error_code,
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "scope": N8N_TEST_RUN_TYPE,
            "test_mode": True,
            "real_business_effect": False,
            **(details or {}),
        },
    )


def _append_event(
    db: Session,
    *,
    job: AutomationJob,
    event_type: str,
    actor_type: str,
    actor_id: str,
    to_status: str | None,
    details: dict[str, object],
) -> None:
    create_n8n_test_event(
        db,
        job=job,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        to_status=to_status,
        details={"test_mode": True, **details},
    )


def _ensure_registry(db: Session, *, timeout_seconds: int) -> None:
    if get_module(db, N8N_TEST_MODULE_KEY) is None:
        create_module(db, _module_payload())
    if get_agent(db, N8N_TEST_AGENT_KEY) is None:
        create_agent(db, _agent_payload())
    if get_workflow(db, N8N_TEST_WORKFLOW_KEY) is None:
        create_workflow(db, _workflow_payload(timeout_seconds))


def run_n8n_test(
    db: Session,
    *,
    user: User,
    audit: AuditContext,
    settings: Settings,
) -> dict[str, Any]:
    run_id = _new_id("run")
    actor_id = str(user.id)
    _ensure_registry(
        db,
        timeout_seconds=settings.n8n_test_request_timeout_seconds,
    )
    db.flush()

    job_id = _new_id("job")
    job = create_job(
        db,
        payload=JobCreate(
            job_id=job_id,
            module_key=N8N_TEST_MODULE_KEY,
            agent_key=N8N_TEST_AGENT_KEY,
            workflow_key=N8N_TEST_WORKFLOW_KEY,
            status="pending",
            risk_level="demo",
            input_payload={
                "run_type": N8N_TEST_RUN_TYPE,
                "test_mode": True,
                "source": "barong_ops_console",
                "external_webhook_kind": "blocked_c11b_mock_only",
                "mock_only": True,
                "external_http_allowed": False,
                "real_business_task": False,
            },
            correlation_id=run_id,
        ),
        requested_by_user_id=user.id,
    )
    db.flush()
    _append_event(
        db,
        job=job,
        event_type="created",
        actor_type="user",
        actor_id=actor_id,
        to_status="pending",
        details={"run_type": N8N_TEST_RUN_TYPE},
    )
    job.started_at = datetime.now(timezone.utc)
    _append_event(
        db,
        job=job,
        event_type="dispatch_started",
        actor_type="test_agent",
        actor_id=N8N_TEST_AGENT_KEY,
        to_status="running",
        details={
            "external_http_attempted": False,
            "external_http_allowed": False,
            "mock_only": True,
        },
    )
    _audit(
        db,
        actor_type="user",
        actor_id=actor_id,
        action="n8n_test.job_created",
        target_type="job",
        target_id=job_id,
        job_id=job_id,
        result="success",
        audit=audit,
        details={
            "status": "running",
            "run_id": run_id,
            "mock_only": True,
            "external_http_attempted": False,
        },
    )

    mock_payload = {
        "job_id": job_id,
        "test_mode": True,
        "source": "barong_ops_console",
        "run_type": N8N_TEST_RUN_TYPE,
        "mock_only": True,
        "external_http_attempted": False,
        "webhook_triggered": False,
    }
    mock_status_code = build_n8n_test_mock_response(payload=mock_payload)

    _append_event(
        db,
        job=job,
        event_type="external_dispatch_blocked",
        actor_type="mock_dispatcher",
        actor_id=MOCK_DISPATCH_ACTOR_ID,
        to_status=None,
        details={
            "mock_status_code": mock_status_code,
            "mock_only": True,
            "external_http_attempted": False,
            "webhook_triggered": False,
            "blocked_by": "c11b_external_execution_lock",
        },
    )

    artifact = create_artifact(
        db,
        ArtifactCreate(
            artifact_id=_new_id("artifact"),
            job_id=job.job_id,
            module_key=N8N_TEST_MODULE_KEY,
            artifact_type="n8n_test_mock_report",
            name="n8n Test Mock Report",
            storage_provider="demo_metadata",
            storage_ref=f"demo/n8n-test/mock/{job_id}",
            status="registered_demo",
            metadata={
                "test_mode": True,
                "mock_only": True,
                "external_storage": False,
                "external_http_attempted": False,
            },
        ),
    )
    db.flush()
    review = create_review(
        db,
        payload=ReviewCreate(
            review_id=_new_id("review"),
            job_id=job.job_id,
            artifact_id=artifact.artifact_id,
            review_type="n8n_test_mock_review",
            risk_level="demo",
            status="pending_demo",
        ),
        requested_by=user.id,
    )
    memory_event = create_memory_event(
        db,
        payload=MemoryEventCreate(
            memory_event_id=_new_id("memory"),
            event_type="n8n_test_mock_completed",
            subject_type="job",
            subject_id=job.job_id,
            job_id=job.job_id,
            payload={
                "summary": (
                    "n8n test run completed in mock-only mode; external "
                    "webhook execution was blocked by C11B."
                ),
                "test_mode": True,
                "mock_only": True,
                "model_called": False,
                "external_http_attempted": False,
            },
            importance="normal_demo",
        ),
        created_by_id=MOCK_DISPATCH_ACTOR_ID,
        created_by_type="mock_dispatcher",
    )
    _append_event(
        db,
        job=job,
        event_type="mock_records_created",
        actor_type="mock_dispatcher",
        actor_id=MOCK_DISPATCH_ACTOR_ID,
        to_status=None,
        details={
            "artifact_id": artifact.artifact_id,
            "review_id": review.review_id,
            "memory_event_id": memory_event.memory_event_id,
            "mock_only": True,
        },
    )

    job.finished_at = datetime.now(timezone.utc)
    _append_event(
        db,
        job=job,
        event_type="completed_demo",
        actor_type="mock_dispatcher",
        actor_id=MOCK_DISPATCH_ACTOR_ID,
        to_status="completed_demo",
        details={
            "terminal_demo_status": True,
            "mock_only": True,
            "external_http_attempted": False,
            "webhook_triggered": False,
        },
    )
    _audit(
        db,
        actor_type="user",
        actor_id=actor_id,
        action="n8n_test.mock_dispatch",
        target_type="job",
        target_id=job_id,
        job_id=job_id,
        result="success",
        audit=audit,
        details={
            "mock_status_code": mock_status_code,
            "external_http_attempted": False,
            "webhook_triggered": False,
            "mock_only": True,
            "blocked_by": "c11b_external_execution_lock",
        },
    )
    db.commit()
    db.refresh(job)
    return _snapshot(db, job=job)


def _callback_is_authorized(
    configured_secret: str,
    provided_secret: str | None,
) -> bool:
    return bool(
        configured_secret
        and provided_secret
        and compare_digest(configured_secret, provided_secret)
    )


def _record_callback_auth_failure(
    db: Session,
    *,
    payload: N8nTestCallbackRequest,
    audit: AuditContext,
) -> None:
    _audit(
        db,
        actor_type="anonymous",
        actor_id="anonymous",
        action="n8n_test.callback",
        target_type="job",
        target_id=payload.job_id,
        job_id=None,
        result="failure",
        error_code="N8N_TEST_CALLBACK_UNAUTHORIZED",
        audit=audit,
        details={"reason": "callback_authentication_failed"},
    )
    db.commit()


def _validate_callback_job(job: AutomationJob | None) -> bool:
    return bool(
        job is not None
        and job.module_id == N8N_TEST_MODULE_KEY
        and job.workflow_id == N8N_TEST_WORKFLOW_KEY
        and job.input_payload.get("run_type") == N8N_TEST_RUN_TYPE
        and job.input_payload.get("test_mode") is True
    )


def process_n8n_test_callback(
    db: Session,
    *,
    payload: N8nTestCallbackRequest,
    provided_secret: str | None,
    settings: Settings,
    audit: AuditContext,
) -> dict[str, Any]:
    configured_secret = _secret_value(settings.n8n_test_callback_secret)
    if not _callback_is_authorized(configured_secret, provided_secret):
        _record_callback_auth_failure(
            db,
            payload=payload,
            audit=audit,
        )
        raise N8nTestCallbackAuthenticationError(
            "Invalid n8n test callback authentication."
        )

    job = get_job(db, payload.job_id)
    if not _validate_callback_job(job):
        _audit(
            db,
            actor_type="mock_callback_guard",
            actor_id=CALLBACK_ACTOR_ID,
            action="n8n_test.callback",
            target_type="job",
            target_id=payload.job_id,
            result="failure",
            error_code="N8N_TEST_CALLBACK_JOB_REJECTED",
            audit=audit,
            details={"reason": "job_is_not_an_n8n_test_run"},
        )
        db.commit()
        raise N8nTestCallbackJobError(
            "The callback job is not an active n8n test bridge run."
        )
    assert job is not None

    if job.status in ALLOWED_TERMINAL_STATUSES:
        _audit(
            db,
            actor_type="mock_callback_guard",
            actor_id=CALLBACK_ACTOR_ID,
            action="n8n_test.callback_duplicate",
            target_type="job",
            target_id=job.job_id,
            job_id=job.job_id,
            result="success",
            audit=audit,
            details={"status": job.status},
        )
        db.commit()
        return _snapshot(db, job=job)

    _append_event(
        db,
        job=job,
        event_type="callback_blocked_mock_only",
        actor_type="mock_callback_guard",
        actor_id=CALLBACK_ACTOR_ID,
        to_status=None,
        details={
            "reported_status": payload.status,
            "run_type": payload.run_type,
            "mock_only": True,
            "external_http_attempted": False,
            "webhook_triggered": False,
            "blocked_by": "c11b_external_execution_lock",
        },
    )
    _audit(
        db,
        actor_type="mock_callback_guard",
        actor_id=CALLBACK_ACTOR_ID,
        action="n8n_test.callback_blocked",
        target_type="job",
        target_id=job.job_id,
        job_id=job.job_id,
        result="success",
        audit=audit,
        details={
            "reported_status": payload.status,
            "terminal_status_changed": False,
            "downstream_triggered": False,
            "external_http_attempted": False,
            "webhook_triggered": False,
            "mock_only": True,
            "blocked_by": "c11b_external_execution_lock",
        },
    )
    db.commit()
    db.refresh(job)
    return _snapshot(db, job=job)


def get_latest_n8n_test(db: Session) -> dict[str, Any] | None:
    job = get_latest_n8n_test_job(db)
    if job is None:
        return None
    return _snapshot(db, job=job)
