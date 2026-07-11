"""Public identity and directory schemas for the C19 application API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class C19AffiliationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    affiliation_id: str
    org_id: str
    org_name: str
    org_type: str
    role: str
    joined_at: datetime


class C19ProfileSummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: int
    display_name: str
    avatar_ref: str | None = None


class C19ProfileRead(C19ProfileSummaryRead):
    bio: str | None = None
    affiliations: list[C19AffiliationRead] = Field(default_factory=list)


class C19DirectoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[C19ProfileRead]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


__all__ = [
    "C19AffiliationRead",
    "C19DirectoryPage",
    "C19ProfileRead",
    "C19ProfileSummaryRead",
]
