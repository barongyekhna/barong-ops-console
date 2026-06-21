from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import FOUNDATION_ID_PATTERN

ReviewDecision = Literal[
    "approve_demo",
    "reject_demo",
    "request_changes_demo",
]


class ReviewCreate(BaseModel):
    review_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=FOUNDATION_ID_PATTERN,
    )
    job_id: str | None = Field(default=None, max_length=128)
    artifact_id: str | None = Field(default=None, max_length=128)
    review_type: str = Field(min_length=1, max_length=100)
    risk_level: str = Field(default="low", min_length=1, max_length=50)
    status: Literal["pending_demo"] = "pending_demo"
    assigned_to: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_subject(self) -> "ReviewCreate":
        if self.job_id is None and self.artifact_id is None:
            raise ValueError("A review requires job_id or artifact_id.")
        return self


class ReviewDecisionCreate(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=4000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: str = Field(exclude=True)
    review_id: str
    job_id: str | None
    artifact_id: str | None
    review_type: str
    risk_level: str
    status: str
    requested_by: int
    assigned_to: int | None
    decided_by: int | None
    decision: str | None
    comment: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewAuditOrganization(BaseModel):
    organization_id: str
    organization_name: str
    organization_type: str
    employee_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    latest_action_at: datetime | None = None


class ReviewAuditEmployee(BaseModel):
    user_id: int
    employee_name: str
    employee_role: str
    job_title: str | None = None
    action_count: int = Field(ge=0)
    latest_action_at: datetime | None = None


class ReviewAuditAction(BaseModel):
    audit_id: str
    organization_id: str
    organization_name: str
    user_id: int
    employee_name: str
    approval_module: str
    operation_type: Literal["同意", "拒绝"]
    status: Literal["approved", "rejected"]
    rejection_reason: str | None = None
    action_time: datetime
    related_object_type: str
    related_object: str
    summary: str
