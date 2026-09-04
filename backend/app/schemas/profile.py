from pydantic import BaseModel, Field

from .user import McpTokenSummary


class ProfileRead(BaseModel):
    user_id: int
    username: str
    display_name: str
    nickname: str | None = None
    avatar_url: str | None = None
    theme_pref: str = "dark"
    skin_pref: str = "cockpit"
    bio: str | None = None


class McpAccessRead(BaseModel):
    """本人 MCP 钥匙状态 + 服务地址;明文从不在这里出现。"""

    summary: "McpTokenSummary"
    eligible: bool
    server_name: str
    server_url: str
    verify_hint: str


class ProfileUpdate(BaseModel):
    """Self-service profile edit. Only fields present in the request are applied."""

    nickname: str | None = Field(default=None, max_length=64)
    theme_pref: str | None = None
    skin_pref: str | None = None
