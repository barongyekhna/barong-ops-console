"""开发信模板库 + 草稿箱。

**验证期刻意不做自动发送**(用户 2026-07-29 拍板):前 30 封的目的是测出
哪句话有人回,没跑出有效模板之前批量发只是批量浪费。所以草稿箱只生成、
只给人过目和复制,发送动作永远在用户手上。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base

DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_SENT = "sent"
DRAFT_STATUS_SKIPPED = "skipped"
DRAFT_STATUSES = (DRAFT_STATUS_DRAFT, DRAFT_STATUS_SENT, DRAFT_STATUS_SKIPPED)


class B2BEmailTemplate(Base):
    """一条模板 = 类型 × 语言 × (店型|全店型通用)。

    只有首封开发信随店型变;跟进信和 5 个回复模板全店型共用——五金店问
    起订量和宠物店问起订量,答案结构一模一样。
    """

    __tablename__ = "b2b_email_templates"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "language",
            "store_type",
            name="uq_b2b_email_templates_combo",
        ),
        CheckConstraint(
            "kind IN ('first_touch', 'follow_up', 'reply_pricing', "
            "'reply_moq', 'reply_sample', 'reply_oem', 'reply_no')",
            name=conv("ck_b2b_email_templates_kind"),
        ),
        Index("ix_b2b_email_templates_kind", "kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    # NULL = 全店型通用。Postgres 的 UNIQUE 对 NULL 不去重,所以内置那条
    # 用空串代替 NULL,保证唯一约束真的生效。
    store_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="",
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 内置模板可以被改,但删不掉——删光了就发不出信了。
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class B2BEmailDraft(Base):
    """一封写好待人工过目的信。**系统永不自动发送。**"""

    __tablename__ = "b2b_email_drafts"
    __table_args__ = (
        UniqueConstraint(
            "prospect_id",
            "kind",
            name="uq_b2b_email_drafts_prospect_kind",
        ),
        CheckConstraint(
            "status IN ('draft', 'sent', 'skipped')",
            name=conv("ck_b2b_email_drafts_status"),
        ),
        Index("ix_b2b_email_drafts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prospect_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=DRAFT_STATUS_DRAFT,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
