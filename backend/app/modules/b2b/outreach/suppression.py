"""永不再发名单。

**为什么必须有**(2026-07-30):跟进模板里写着"回复 no thanks 我就不烦你了",
但系统里没有任何地方记这件事——下一轮生成草稿还会给他生成。一个说过"别发了"
还继续收到信的人会直接点「举报垃圾邮件」,而投诉率一高
`barongsupply.com` 就废了(用户红线:退信/投诉率 >3% 杀域名)。

刚买的域名正准备养,这条不补上等于养好了再自己砸掉。

**设计上的两个决定**:

1. **独立一张表,不做成 prospect 上的一个字段。** 说"别发了"的人可能根本
   不在候选池里(转发来的、我们删过的行、手填的地址)。名单要能收住任何邮箱,
   而且**候选行删了名单也不能跟着没**。
2. **按规范化后的邮箱匹配**:大小写、首尾空白、Gmail 的 `+tag` 全部归一。
   否则 `Bob@Shop.com` 退订了,`bob@shop.com` 照样能收到。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import Uuid

from ....db.base import Base

# 谁把这个地址加进名单的。
SOURCE_REPLY = "reply"  # 对方回信说别发了
SOURCE_BOUNCE = "bounce"  # 退信/地址不存在
SOURCE_MANUAL = "manual"  # 人工判断
SOURCES = (SOURCE_REPLY, SOURCE_BOUNCE, SOURCE_MANUAL)


class B2BSuppression(Base):
    """一个永不再发的邮箱。

    **只增不减是刻意的**:退订是对方的意思表示,不该被一次误操作抹掉。要恢复
    得显式删除(留了 `remove()`,但界面上不给按钮)。
    """

    __tablename__ = "b2b_suppressions"
    __table_args__ = (
        Index("ix_b2b_suppressions_email", "email", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 规范化后的地址(小写、去空白、去 +tag),匹配就按这个字段
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # 原样留一份,方便人看清对方到底写的什么
    raw_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def normalise(email: str | None) -> str:
    """归一化,用来匹配。

    `Bob+Store@Gmail.COM` → `bob@gmail.com`。不归一的话同一个人换个大小写
    或加个 +tag 就又能收到信了。
    """
    text = str(email or "").strip().lower()
    if "@" not in text:
        return ""
    local, _, domain = text.rpartition("@")
    local = local.split("+", 1)[0]
    if not local or not domain:
        return ""
    return f"{local}@{domain}"


def is_suppressed(db: Session, email: str | None) -> bool:
    key = normalise(email)
    if not key:
        return False
    return (
        db.scalar(select(B2BSuppression.id).where(B2BSuppression.email == key))
        is not None
    )


def suppressed_set(db: Session) -> set[str]:
    """一次取全量,给批量生成用——逐条查库在 100 个候选上就是 100 次往返。"""
    return {row for row in db.scalars(select(B2BSuppression.email)) if row}


def add(
    db: Session,
    *,
    email: str,
    source: str = SOURCE_MANUAL,
    note: str | None = None,
) -> B2BSuppression | None:
    """加进名单。已在名单里就原样返回,不重复建行、不报错。"""
    key = normalise(email)
    if not key:
        return None
    if source not in SOURCES:
        source = SOURCE_MANUAL
    existing = db.scalar(
        select(B2BSuppression).where(B2BSuppression.email == key)
    )
    if existing is not None:
        return existing
    row = B2BSuppression(
        email=key,
        raw_email=str(email).strip()[:320] or None,
        source=source,
        note=(note or None),
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def remove(db: Session, *, email: str) -> bool:
    """极少用:对方明确说"重新加回来"才该调。界面上不给按钮。"""
    key = normalise(email)
    if not key:
        return False
    row = db.scalar(select(B2BSuppression).where(B2BSuppression.email == key))
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def listing(db: Session, *, limit: int = 200) -> list[B2BSuppression]:
    return list(
        db.scalars(
            select(B2BSuppression)
            .order_by(B2BSuppression.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
