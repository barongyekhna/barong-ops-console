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
