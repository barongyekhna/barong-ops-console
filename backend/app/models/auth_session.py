from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin
from .user import User


class AuthSession(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auth_sessions"

    session_id_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    # 这个会话当前选定的组织。为空 = 还没选，解析链继续往下走
    # （唯一成员关系 → user.organization_id → 名下拥有的组织）。
    #
    # 2026-08-31 体检：middleware/org_context.py 一直在读
    # `auth_session.active_org_id`，**而这一列根本不存在** —— 于是「会话选定组织」
    # 那条分支永不执行，多组织用户被整站 403 锁死且无自救出口。
    active_org_id: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    invalidation_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    user: Mapped[User] = relationship(User)
