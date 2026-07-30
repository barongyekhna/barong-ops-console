"""样品费抵扣台账。

**这是补欠账,不是新功能。** 我们在**四个地方**跟买家承诺过同一句话:

    "样品收费,但全额抵扣首单——所以你只要下单,样品等于免费。"

产品页小窗、批发页、图册最后一页、开发信回复,全写着。可系统里**没有任何
地方记"谁付过样品费、抵了没有"**。

第一个客户你记得住。第三个就开始虚:他两个月前买过样品,现在下单说"你说过
抵扣的",你翻不到记录——要么白送(亏钱),要么让他证明(伤感情)。

**按完整邮箱认人**,和退订名单同一条规矩(见 `outreach/suppression.py`):
小店老板多用 gmail/outlook,按域名认会把张三的样品费抵给李四。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import Uuid

from ....db.base import Base
from ..outreach.suppression import normalise


class B2BSampleCredit(Base):
    """一笔已付的样品费。用掉之后**不删行**,只标记——台账要能回溯。"""

    __tablename__ = "b2b_sample_credits"
    __table_args__ = (Index("ix_b2b_sample_credits_email", "buyer_email"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 规范化后的邮箱,匹配按这个字段
    buyer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    buyer_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 抵进了哪张单;为空 = 还没用
    consumed_document_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def record(
    db: Session,
    *,
    buyer_email: str,
    amount: Decimal,
    buyer_company: str | None = None,
    paid_on: date | None = None,
    note: str | None = None,
    currency: str = "USD",
) -> B2BSampleCredit | None:
    key = normalise(buyer_email)
    if not key or Decimal(str(amount)) <= 0:
        return None
    row = B2BSampleCredit(
        buyer_email=key,
        buyer_company=(buyer_company or None),
        amount=Decimal(str(amount)),
        currency=currency,
        paid_on=paid_on or datetime.now(UTC).date(),
        note=(note or None),
    )
    db.add(row)
    db.flush()
    return row


def _open_rows(db: Session, buyer_email: str) -> list[B2BSampleCredit]:
    key = normalise(buyer_email)
    if not key:
        return []
    return list(
        db.scalars(
            select(B2BSampleCredit)
            .where(B2BSampleCredit.buyer_email == key)
            .where(B2BSampleCredit.consumed_document_id.is_(None))
            .order_by(B2BSampleCredit.paid_on)
        )
    )


def available(db: Session, buyer_email: str | None) -> Decimal:
    """这个买家还有多少样品费没抵。"""
    return sum(
        (row.amount for row in _open_rows(db, buyer_email or "")),
        Decimal("0"),
    )


def consume(
    db: Session, *, buyer_email: str | None, document_id: UUID, cap: Decimal
) -> Decimal:
    """把可用额度抵进一张单,返回实际抵掉多少。

    **抵扣不超过货款**(`cap`):抵成负数就变成我们倒欠钱,那张单没法看。
    抵不完的留着——他下次还能用,承诺是"全额抵扣"不是"用一次作废"。
    """
    remaining = Decimal(str(cap))
    used = Decimal("0")
    now = datetime.now(UTC)
    for row in _open_rows(db, buyer_email or ""):
        if remaining <= 0:
            break
        if row.amount > remaining:
            # 这一笔比剩余货款还大:留着不动,下次整笔用。**不做拆分**——
            # 拆了台账就对不上"这笔样品费到底抵没抵过"。
            continue
        row.consumed_document_id = document_id
        row.consumed_at = now
        used += row.amount
        remaining -= row.amount
    if used:
        db.flush()
    return used


def listing(db: Session, *, limit: int = 200) -> list[B2BSampleCredit]:
    return list(
        db.scalars(
            select(B2BSampleCredit)
            .order_by(B2BSampleCredit.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
