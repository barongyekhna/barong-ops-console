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


class SqhDigest(Base):
    """运营看板(10-30):一天一行(kind=day, period_key=2026-10-29)、一周一行(kind=week, period_key=2026-W44)。
    payload 是各路数 + 给面板画的 sections;findings 是规则层算出的异常。接口和面板只读它,不现算。"""

    __tablename__ = "sqh_digests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    findings: Mapped[Any] = mapped_column(_json(), nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SqhGscPage(Base):
    """Search Console 一天 × 一个落地页的表现(11-03 改:站小,按天的搜索词谷歌全部匿名,「词×页」永远是空;按页不匿名)。只读谷歌给的数。"""

    __tablename__ = "sqh_gsc_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    page: Mapped[str] = mapped_column(String(1000), nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctr: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False, default=0)
    position: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)


class SqhGscQuery(Base):
    """搜索词按窗口拉(11-03):截止 window_end 的近 window_days 天,一个词一行。词的匿名门槛按窗口算,窗口越长露出来的词越多。"""

    __tablename__ = "sqh_gsc_queries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    window_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctr: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False, default=0)
    position: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)


class SqhGscDay(Base):
    """哪几天拉过了(一天没有任何展现也要记,不然天天重拉):rows = 页面行数、status ok/failed、error。

    11-03 起这一行还存当天全站合计(clicks/impressions/ctr/position,含被匿名的词——比按页加起来准),
    fmt=2 才算新口径拉过(旧的 fmt=1 只拉了「词×页」,自动重拉);window_rows = 截止这天的 28 天搜索词窗口拉到几行(None = 没拉)。"""

    __tablename__ = "sqh_gsc_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    fmt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    ctr: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False, default=0, server_default="0")
    position: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0, server_default="0")
    window_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SqhRouteRecord(Base):
    """选风格包的记录(M2a,交接 12 第三部分第 5、8 节):一个品判一次一行,record 是整份 jiagui-route/1。

    流水线只认 purpose=pipeline 的最新一行;purpose=replay 是「风格包待生效」卡试算的(装了新包以后结果会不会变),不算数。
    facts 存的是当时喂给模型的资料原文——试算时原样再判一次,不用回头拼资料。"""

    __tablename__ = "sqh_route_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dossier_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="pipeline")
    replay_for: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # jiagui_packs.id
    registry_fp: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    price: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    facts: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pack_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    missing_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    record: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    card_ref: Mapped[str | None] = mapped_column(String(8), nullable=True)
    owner_pick: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 两个包同分,老板选的那个
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
