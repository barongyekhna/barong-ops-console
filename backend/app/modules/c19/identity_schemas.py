"""Public identity and directory schemas for the C19 application API."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    is_bot: bool = False


class C19ProfileRead(C19ProfileSummaryRead):
    bio: str | None = None
    affiliations: list[C19AffiliationRead] = Field(default_factory=list)


class C19ProfileUpdate(BaseModel):
    """Fields an authenticated user may change on their own C19 profile."""

    model_config = ConfigDict(extra="forbid")

    avatar_ref: str | None = Field(max_length=512)

    @field_validator("avatar_ref", mode="before")
    @classmethod
    def normalize_safe_avatar_ref(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        if any(
            unicodedata.category(character).startswith("C")
            for character in value
        ):
            raise ValueError("Avatar reference contains a control character.")

        normalized = value.strip()
        if not normalized:
            raise ValueError("Avatar reference must not be blank.")
        if any(character.isspace() for character in normalized) or "\\" in normalized:
            raise ValueError("Avatar reference is invalid.")

        if normalized.startswith("/"):
            if normalized.startswith("//"):
                raise ValueError("Avatar reference must be a same-origin path.")
            return normalized

        try:
            parsed = urlsplit(normalized)
            parsed_port = parsed.port
        except ValueError:
            raise ValueError("Avatar reference URL is invalid.") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed_port is not None and not 1 <= parsed_port <= 65535
        ):
            raise ValueError(
                "Avatar reference must be an HTTPS URL or same-origin path."
            )
        return normalized


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
    "C19ProfileUpdate",
]
