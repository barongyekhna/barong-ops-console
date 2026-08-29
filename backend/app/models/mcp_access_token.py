"""每个真人账号一把 MCP 个人钥匙(外部桌面代理——Codex 等——经 MCP 接入控制台时的身份)。

- 只存 sha256 哈希 + 展示前缀,明文只在生成/重置那一刻回给人一次(与登录会话、
  初始密码同一做法)。
- 一人一把(``user_id`` 唯一);重置 = 覆盖哈希;停用 = ``status='disabled'``,
  每次请求查库,即刻生效。
- 钥匙只证明「你是谁」,不带任何权限——各 MCP 服务按该人现有的模块权限放行。
  所以表名、字段都与 K 无关,下一个模块开 MCP 口子直接复用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type
from .user import User

TOKEN_STATUS_ACTIVE = "active"
TOKEN_STATUS_DISABLED = "disabled"


class McpAccessToken(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_access_tokens"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=TOKEN_STATUS_ACTIVE,
        server_default=TOKEN_STATUS_ACTIVE,
    )
    issued_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", json_type(), nullable=False, default=dict, server_default="{}"
    )

    user: Mapped[User] = relationship(User)
