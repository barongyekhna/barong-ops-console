from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .artifacts import ArtifactResponse
from .errors import SystemErrorResponse
from .jobs import JobEventResponse, JobResponse
from .memory import MemoryEventResponse
from .reviews import ReviewResponse


class N8nTestCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=128)
    run_type: Literal["n8n_test_bridge"]
    test_mode: Literal[True] = True
    status: Literal["completed_demo", "failed"]


class N8nTestJobResponse(JobResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    run_type: Literal["n8n_test_bridge"]


class N8nTestArtifactResponse(ArtifactResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    title: str


class N8nTestMemoryEventResponse(MemoryEventResponse):
    summary: str


class N8nTestSnapshotResponse(BaseModel):
    test_mode: Literal[True] = True
    job: N8nTestJobResponse
    latest_event: JobEventResponse | None
    artifact: N8nTestArtifactResponse | None
    review: ReviewResponse | None
    memory_event: N8nTestMemoryEventResponse | None
    error: SystemErrorResponse | None
    operation_log_count: int


class N8nTestRunResponse(N8nTestSnapshotResponse):
    pass


class N8nTestLatestResponse(N8nTestSnapshotResponse):
    pass


class N8nTestCallbackResponse(N8nTestSnapshotResponse):
    pass
