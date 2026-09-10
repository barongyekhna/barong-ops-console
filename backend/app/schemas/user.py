import secrets
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ..core.roles import get_role_display_metadata, normalize_role

ManagedUserRole = str

# Length of the one-time random initial password handed to the creator when a
# managed user is created. Kept comfortably above the 12-char minimum enforced
# by change-password / reset-password so the account is never seeded with a
# guessable secret like "123456".
INITIAL_PASSWORD_LENGTH = 16


def generate_initial_password() -> str:
    """Return a random, URL-safe one-time initial password (no fixed default).

    Replaces the old fixed "123456" default so a newly created account cannot
    be taken over by anyone who merely knows the username. The plaintext is
    returned to the creator exactly once (never stored in cleartext).
    """
    return secrets.token_urlsafe(INITIAL_PASSWORD_LENGTH)


USER_MANAGEMENT_ROLES = (
    "owner",
    "super_admin",
    "operator",
    "viewer",
    "reviewer",
)
PASSWORD_RESET_BYPASS_ROLES = frozenset(("owner",))


def is_user_manager_role(role: str) -> bool:
    return normalize_role(role) in {"owner", "super_admin"}


def role_bypasses_password_reset(role: str | None) -> bool:
    if role is None:
        return False
    return normalize_role(role) in PASSWORD_RESET_BYPASS_ROLES


def must_change_password_required(
    *,
    role: str | None,
    must_change_password: bool,
) -> bool:
    return bool(must_change_password) and not role_bypasses_password_reset(role)


def initial_must_change_password_for_role(role: str | None) -> bool:
    return not role_bypasses_password_reset(role)


def validate_user_management_role(role: str) -> str:
    normalized = normalize_role(role)
    if normalized not in USER_MANAGEMENT_ROLES:
        allowed = ", ".join(USER_MANAGEMENT_ROLES)
        raise ValueError(f"Role must be one of: {allowed}.")
    return normalized


def user_management_role_metadata() -> list[dict[str, object]]:
    metadata: list[dict[str, object]] = []
    for role in USER_MANAGEMENT_ROLES:
        role_metadata = get_role_display_metadata(role)
        role_metadata["assignable"] = True
        metadata.append(role_metadata)
    return metadata


class UserMembershipRead(BaseModel):
    org_id: str
    org_name: str
    role: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    title: str | None = None
    job_title: str | None = None
    organization: str | None = None
    organization_id: str | None = None
    # 全部 active 成员关系(含主组织)。owner 不挂组织,这里为空。
    memberships: list[UserMembershipRead] = []
    must_change_password: bool
    is_active: bool
    is_bot: bool = False
    display_name: str | None = None
    nickname: str | None = None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    mcp_token: "McpTokenSummary | None" = None
    # 头像(C19 资料 avatar_ref,可直接当 img src);没有则 None。
    avatar_url: str | None = None

    @field_validator("role")
    @classmethod
    def normalize_response_role(cls, value: str) -> str:
        return normalize_role(value)

    @model_validator(mode="after")
    def sync_standard_fields(self) -> "UserResponse":
        self.title = self.job_title
        self.organization = self.organization_id
        return self


class McpTokenSummary(BaseModel):
    """MCP 个人钥匙状态(永远不含明文)。"""

    has_token: bool = False
    status: str | None = None
    token_prefix: str | None = None
    rotated_at: datetime | None = None
    last_used_at: datetime | None = None


class UserCreateResponse(UserResponse):
    """Response for user creation. Carries the one-time initial password (and
    the one-time MCP personal token) so the creator can pass them to the new
    user. Only ever populated on creation."""

    initial_password: str | None = None
    mcp_token_secret: str | None = None


class McpTokenLogItem(BaseModel):
    """一条钥匙操作记录(发放/重置/停用/启用),id 已解析成用户名。"""

    id: int
    action: str
    actor_id: str | None = None
    actor_username: str | None = None
    target_id: str | None = None
    target_username: str | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime


class McpTokenLogResponse(BaseModel):
    items: list[McpTokenLogItem]
    count: int


class McpTokenIssueResponse(BaseModel):
    """一次性回明文钥匙 + 装机命令;之后只剩哈希,再看不到。"""

    token: str
    summary: McpTokenSummary
    setup_command_mac: str
    setup_command_windows: str
    server_name: str
    server_url: str
    verify_hint: str


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    role: ManagedUserRole
    job_title: str | None = Field(default=None, max_length=255)
    organization_id: str | None = Field(default=None, max_length=40)
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        return validate_user_management_role(value)

    @model_validator(mode="after")
    def normalize_fields(self) -> "UserCreate":
        self.username = self.username.strip()
        if not self.username:
            raise ValueError("Username must not be empty.")
        if self.job_title is not None:
            self.job_title = self.job_title.strip() or None
        if self.organization_id is not None:
            self.organization_id = self.organization_id.strip() or None
        if self.role == "owner":
            self.job_title = None
            self.organization_id = None
        elif self.organization_id is None:
            raise ValueError("Organization is required for non-owner users.")
        return self


class UserUpdate(BaseModel):
    role: ManagedUserRole | None = None
    is_active: bool | None = None
    # 岗位与主组织(2026-09-10 起可改)。主组织换了会自动补上该组织的成员关系,
    # 旧组织的成员关系不动——多组织成员在「组织」区单独勾选。
    job_title: str | None = Field(default=None, max_length=255)
    organization_id: str | None = Field(default=None, max_length=40)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_user_management_role(value)

    @field_validator("job_title", "organization_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdate":
        if (
            self.role is None
            and self.is_active is None
            and self.job_title is None
            and self.organization_id is None
        ):
            raise ValueError("At least one user field must be supplied.")
        return self


class PasswordResetRequest(BaseModel):
    new_password: SecretStr = Field(min_length=12, max_length=256)


class UserRoleResponse(BaseModel):
    name: str
    label: str
    description: str
    human_or_agent: str
    c04_status: str
    assignable: bool


class UserRolesResponse(BaseModel):
    assignable_roles: list[UserRoleResponse]
    standard_roles: list[UserRoleResponse]


class BotCreate(BaseModel):
    """注册数字员工。角色固定 viewer + is_bot,零权限码;密码给 worker 登录用。"""

    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=64)
    job_title: str = Field(min_length=1, max_length=255)
    organization_id: str = Field(min_length=1, max_length=40)
    bio: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=12, max_length=128)


class UserPurgeResponse(BaseModel):
    user_id: int
    username: str
    role: str
    is_bot: bool
    removed: dict[str, int]
