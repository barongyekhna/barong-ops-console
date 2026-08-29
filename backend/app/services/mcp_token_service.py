"""MCP 个人钥匙(模块无关):生成 / 重置 / 停用 / 启用 / 按钥匙认人。

设计拍板 2026-08-28:
- 每个真人账号一把;机器人不发(它们有自己的 worker 身份)。
- 只存哈希,明文只回一次;忘了就重置。
- 钥匙 ≠ 权限:各 MCP 服务用 :func:`resolve_user_by_token` 拿到 User 之后,
  按那个人现有的模块权限放行。
- 谁能管别人的钥匙 = 谁能管那个用户(沿用用户管理的门)。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.mcp_access_token import (
    TOKEN_STATUS_ACTIVE,
    TOKEN_STATUS_DISABLED,
    McpAccessToken,
)
from ..models.user import User
from .auth_service import AuditContext
from .user_management_service import (
    BotOperationNotAllowedError,
    _ensure_actor_can_manage_user,
    _log_user_operation,
    get_managed_user,
)

TOKEN_PREFIX = "bk_"
# 展示用前缀长度(含 bk_):够人认出是哪把,不够拿去猜。
DISPLAY_PREFIX_LEN = 12
LAST_USED_WRITE_THROTTLE = timedelta(minutes=5)

MCP_SERVER_NAME = "barong_k_images"
MCP_TOKEN_ENV_VAR = "BARONG_K_MCP_TOKEN"


class McpTokenNotForBotsError(BotOperationNotAllowedError):
    """机器人账号不发个人钥匙。"""


def _now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def display_prefix(token: str) -> str:
    return token[:DISPLAY_PREFIX_LEN]


# --- 对外基址 / 装机命令(K 是第一个接入的 MCP 服务;URL 由它决定) --------------


def public_base_url() -> str:
    return (os.getenv("K_MCP_PUBLIC_BASE_URL") or "https://ops.barongyekhna.com").rstrip("/")


def mcp_endpoint_url() -> str:
    return f"{public_base_url()}/mcp/k-images"


def setup_command_mac(token: str) -> str:
    return f"curl -fsSL {mcp_endpoint_url()}/setup.sh | bash -s -- {token}"


def setup_command_windows(token: str) -> str:
    return (
        "powershell -NoProfile -ExecutionPolicy Bypass -Command "
        f"\"& ([scriptblock]::Create((irm {mcp_endpoint_url()}/setup.ps1))) -Token '{token}'\""
    )


def install_commands(token: str) -> dict[str, str]:
    return {"mac": setup_command_mac(token), "windows": setup_command_windows(token)}


VERIFY_HINT = "重启 Codex 后新建对话,输入 /mcp,应看到 barong_k_images 下的工具。"


# --- 查 -------------------------------------------------------------------------


def get_token_row(db: Session, user_id: int) -> McpAccessToken | None:
    return db.scalars(
        select(McpAccessToken).where(McpAccessToken.user_id == user_id).limit(1)
    ).first()


def token_summary(row: McpAccessToken | None) -> dict[str, Any]:
    if row is None:
        return {
            "has_token": False,
            "status": None,
            "token_prefix": None,
            "rotated_at": None,
            "last_used_at": None,
        }
    return {
        "has_token": True,
        "status": row.status,
        "token_prefix": row.token_prefix,
        "rotated_at": row.rotated_at,
        "last_used_at": row.last_used_at,
    }


def summaries_for_users(db: Session, user_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not user_ids:
        return {}
    rows = db.scalars(
        select(McpAccessToken).where(McpAccessToken.user_id.in_(user_ids))
    ).all()
    by_user = {row.user_id: row for row in rows}
    return {uid: token_summary(by_user.get(uid)) for uid in user_ids}


# --- 发 / 重置 / 停 / 启 ---------------------------------------------------------


@dataclass(frozen=True)
class IssuedToken:
    token: str  # 明文,只此一次
    row: McpAccessToken


def mint_token(
    db: Session,
    *,
    user: User,
    actor: User,
    audit: AuditContext | None,
    reason: str = "issue",
) -> IssuedToken:
    """生成一把新钥匙(首次=issue,再次=reset),覆盖该用户唯一行。不 commit。"""
    if user.is_bot:
        raise McpTokenNotForBotsError("Bot accounts do not get MCP personal tokens.")
    token = generate_token()
    row = get_token_row(db, user.id)
    is_new = row is None
    if row is None:
        row = McpAccessToken(user_id=user.id, rotated_at=_now())
    row.token_hash = hash_token(token)
    row.token_prefix = display_prefix(token)
    row.status = TOKEN_STATUS_ACTIVE
    row.issued_by_user_id = actor.id
    row.rotated_at = _now()
    row.disabled_at = None
    row.disabled_by_user_id = None
    db.add(row)
    db.flush()
    if audit is not None:
        _log_user_operation(
            db,
            actor=actor,
            action="mcp_token.issue" if is_new else "mcp_token.reset",
            target=user,
            audit=audit,
            details={"token_prefix": row.token_prefix, "reason": reason},
        )
    return IssuedToken(token=token, row=row)


def _set_status(
    db: Session,
    *,
    user: User,
    actor: User,
    audit: AuditContext | None,
    status: str,
) -> McpAccessToken:
    row = get_token_row(db, user.id)
    if row is None:
        # 停用一把不存在的钥匙 = 先占位再停;启用一把不存在的 = 直接发一把新的没意义,
        # 统一先建行(无明文,哈希随机不可用)再按状态处理,保证「停用」永远可执行。
        row = McpAccessToken(
            user_id=user.id,
            token_hash=hash_token(generate_token()),
            token_prefix="bk_(未发)",
            rotated_at=_now(),
            issued_by_user_id=actor.id,
        )
    row.status = status
    if status == TOKEN_STATUS_DISABLED:
        row.disabled_at = _now()
        row.disabled_by_user_id = actor.id
    else:
        row.disabled_at = None
        row.disabled_by_user_id = None
    db.add(row)
    db.flush()
    if audit is not None:
        _log_user_operation(
            db,
            actor=actor,
            action=f"mcp_token.{'disable' if status == TOKEN_STATUS_DISABLED else 'enable'}",
            target=user,
            audit=audit,
            details={"token_prefix": row.token_prefix},
        )
    return row


# 管理者视角(用户管理页):沿用「谁能管这个用户」的门;这些函数自己 commit。


def reset_token_for_user(db: Session, *, user_id: int, actor: User, audit: AuditContext) -> IssuedToken:
    user = get_managed_user(db, user_id)
    _ensure_actor_can_manage_user(actor, user)
    issued = mint_token(db, user=user, actor=actor, audit=audit, reason="manager_reset")
    db.commit()
    db.refresh(issued.row)
    return issued


def disable_token_for_user(db: Session, *, user_id: int, actor: User, audit: AuditContext) -> McpAccessToken:
    user = get_managed_user(db, user_id)
    _ensure_actor_can_manage_user(actor, user)
    row = _set_status(db, user=user, actor=actor, audit=audit, status=TOKEN_STATUS_DISABLED)
    db.commit()
    db.refresh(row)
    return row


def enable_token_for_user(db: Session, *, user_id: int, actor: User, audit: AuditContext) -> McpAccessToken:
    user = get_managed_user(db, user_id)
    _ensure_actor_can_manage_user(actor, user)
    row = _set_status(db, user=user, actor=actor, audit=audit, status=TOKEN_STATUS_ACTIVE)
    db.commit()
    db.refresh(row)
    return row


def reset_own_token(db: Session, *, user: User, audit: AuditContext) -> IssuedToken:
    """本人重置自己的钥匙。被管理者停用的钥匙本人不能靠重置复活。"""
    row = get_token_row(db, user.id)
    if row is not None and row.status == TOKEN_STATUS_DISABLED:
        raise BotOperationNotAllowedError("你的 MCP 钥匙已被管理员停用,请联系管理员启用。")
    issued = mint_token(db, user=user, actor=user, audit=audit, reason="self_reset")
    db.commit()
    db.refresh(issued.row)
    return issued


# --- 认人(MCP sidecar 每次请求调用) --------------------------------------------


def resolve_user_by_token(
    db: Session,
    presented: str,
    *,
    ip_address: str | None = None,
) -> User | None:
    """明文钥匙 → User;钥匙不存在/已停用/账号停用/机器人 → None(fail-closed)。
    顺手记 last_used(5 分钟节流,避免每次请求都写)。调用方负责 commit。"""
    value = (presented or "").strip()
    if not value.startswith(TOKEN_PREFIX) or len(value) < 20:
        return None
    digest = hash_token(value)
    row = db.scalars(
        select(McpAccessToken).where(McpAccessToken.token_hash == digest).limit(1)
    ).first()
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        return None
    if row.status != TOKEN_STATUS_ACTIVE:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.is_bot:
        return None
    now = _now()
    if row.last_used_at is None or now - row.last_used_at > LAST_USED_WRITE_THROTTLE:
        row.last_used_at = now
        row.last_used_ip = (ip_address or "")[:45] or None
        db.add(row)
    return user


__all__ = [
    "IssuedToken",
    "MCP_SERVER_NAME",
    "MCP_TOKEN_ENV_VAR",
    "McpTokenNotForBotsError",
    "VERIFY_HINT",
    "disable_token_for_user",
    "enable_token_for_user",
    "get_token_row",
    "hash_token",
    "install_commands",
    "mcp_endpoint_url",
    "mint_token",
    "reset_own_token",
    "reset_token_for_user",
    "resolve_user_by_token",
    "summaries_for_users",
    "token_summary",
]
