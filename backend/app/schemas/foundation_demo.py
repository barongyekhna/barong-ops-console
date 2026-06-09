from typing import Literal

from pydantic import BaseModel, ConfigDict

from .artifacts import ArtifactResponse
from .jobs import JobEventResponse, JobResponse
from .memory import MemoryEventResponse
from .registry import AgentResponse, ModuleResponse, WorkflowResponse
from .reviews import ReviewResponse


class FoundationDemoWorkflowResponse(WorkflowResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    trigger_type: Literal["internal_demo"]


class FoundationDemoJobResponse(JobResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    job_type: Literal["foundation_demo"]


class FoundationDemoArtifactResponse(ArtifactResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    title: str


class FoundationDemoMemoryEventResponse(MemoryEventResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    summary: str


class FoundationDemoOperationLogSummary(BaseModel):
    operation_id: str
    action: str
    target_type: str
    target_id: str
    result: str


class FoundationDemoSnapshotResponse(BaseModel):
    job: FoundationDemoJobResponse
    events_count: int
    artifact: FoundationDemoArtifactResponse | None
    review: ReviewResponse | None
    memory_event: FoundationDemoMemoryEventResponse | None
    operation_log_count: int


class FoundationDemoRunResponse(FoundationDemoSnapshotResponse):
    module: ModuleResponse
    agent: AgentResponse
    workflow: FoundationDemoWorkflowResponse
    job_events: list[JobEventResponse]
    operation_logs: list[FoundationDemoOperationLogSummary]


class FoundationDemoLatestResponse(FoundationDemoSnapshotResponse):
    pass
