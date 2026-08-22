from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, false, true
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin


class User(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        index=True,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    # Digital-employee accounts (e.g. 白苏婉).  Deliberately a separate flag
    # rather than role="bot_agent": rbac.py maps that legacy role to
    # ROLE_SYSTEM, which only grants ACTION_INTERNAL and would strip the bot
    # of even its own read permissions.  This flag is a label, never a gate.
    is_bot: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_failed_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
