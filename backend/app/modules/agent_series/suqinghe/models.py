"""苏青禾的表。

家规 14 同理:**没有任何一列叫 ``org_id``**。办公室是全站任何登录的人都能看的,
C18G 会按会话组织自动过滤带 org_id 的模型,别的组织的同事就什么都看不到了。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Integer, LargeBinary, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ....db.base import Base


def _json() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


class SqhCard(Base):
    """审批卡。网页 / C19 / MCP 都只通过 cards.decide_card 改它。"""

    __tablename__ = "sqh_cards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 对外的短号(C19 里说「批 #a3f9」),4 位十六进制,和霓旌的卡一个习惯。
    ref: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    if_not: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    evidence: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    decided_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_via: Mapped[str | None] = mapped_column(String(8), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SqhMemory(Base):
    """硬记忆:计划、建议、决定、口述、观察。按问题检索,不允许失忆。"""

    __tablename__ = "sqh_memory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    refs: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    actor_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SqhGoal(Base):
    __tablename__ = "sqh_goals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 可度量的指标,如 {"metric": "published_products", "target": 30};没有就空,只当文字目标。
    metric: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SqhActivity(Base):
    """流水:办公室里滚动显示她在干什么。"""

    __tablename__ = "sqh_activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="work")
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SqhState(Base):
    """单行(id=1):暂停开关 + 她此刻在干什么。"""

    __tablename__ = "sqh_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activity: Mapped[str] = mapped_column(String(16), nullable=False, default="working")
    task: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muted_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_spoke_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_plan_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SqhSnapshot(Base):
    __tablename__ = "sqh_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    payload: Mapped[Any] = mapped_column(_json(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SqhDossier(Base):
    """一个 1688 链接 → 一份 K 档案草稿(10-23 第一项真本事)。批卡才真的建进 K。"""

    __tablename__ = "sqh_dossiers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # queued → fetching → reading → ready → created;旁路:blocked / failed / rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    requested_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str] = mapped_column(String(8), nullable=False, default="web")
    capture: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    draft: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Any] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    card_ref: Mapped[str | None] = mapped_column(String(8), nullable=True)
    k_product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SqhBrowser(Base):
    """单行(id=1):她的登录浏览器此刻什么状态(10-28)。画面(JPEG)也放这儿——后端和 worker 只共享数据库;
    只在有人看(viewer_seen_at 5 秒内)时才写帧。"""

    __tablename__ = "sqh_browser"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # idle / fetching / needs_human(等老板过验证) / interactive(老板在登录) / asking_seller(在问卖家)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dossier_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    frame: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewer_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logged_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SqhBrowserInput(Base):
    """老板在「浏览器」面板里的一下点击/一次输入(owner 才能写),worker 每 100ms 取走应用到页面上。"""

    __tablename__ = "sqh_browser_inputs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
