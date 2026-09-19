"""RD 系列 · 远程桌面的 SQLAlchemy 模型。

四张表分四件事:``rd_devices`` 是谁的哪台机器、``rd_unattended_grants`` 是「公用机
放谁免同意进」、``rd_sessions`` 是每一次操控的完整台账、``rd_signals`` 是 WebRTC
握手时两边互递的信封(建连一结束就没用了)。

**刻意不带 ``org_id`` 列。** 这个模块按用户拍板是「不属于任何组织、所有登录用户都能
用」,而带 ``org_id`` 的模型会被 C18G 数据隔离自动按当前组织盖一层,那正好是这里不
要的东西。归属只认 ``owner_user_id``——人,不是公司。

``device_uuid`` 由被控端客户端自己生成并持久化在它的 userData 里,**刻意不复用 VPN
那个设备 UUID**:那个 UUID 由高权限的 VPN 服务生成,取它就等于逼着「只想用远程桌面」
的人先装一遍 VPN 组件。两者互不依赖。

台账(``rd_sessions``)只增不改:被拒绝、超时、断开都是往同一行上补时间戳和 end_reason,
永远不删行——「谁在什么时候连过谁」这件事必须查得到。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ...db.base import Base

# ---------------------------------------------------------------------------
# 会话状态机
#
#   requested ──同意──▶ consented ──画面通了──▶ active ──▶ ended
#       │                                                   ▲
#       ├──拒绝──▶ denied ──────────────────────────────────┘(终态)
#       └──60 秒没人理──▶ expired(终态)
#
# 终态三个:denied / expired / ended。进了终态的行不再变,只能新开一条。
# ---------------------------------------------------------------------------
STATE_REQUESTED = "requested"
STATE_CONSENTED = "consented"
STATE_ACTIVE = "active"
STATE_DENIED = "denied"
STATE_EXPIRED = "expired"
STATE_ENDED = "ended"
ALLOWED_STATES = (
    STATE_REQUESTED,
    STATE_CONSENTED,
    STATE_ACTIVE,
    STATE_DENIED,
    STATE_EXPIRED,
    STATE_ENDED,
)
TERMINAL_STATES = (STATE_DENIED, STATE_EXPIRED, STATE_ENDED)
# 还占着被控机、不允许再开第二条的状态
LIVE_STATES = (STATE_REQUESTED, STATE_CONSENTED, STATE_ACTIVE)

# 这次进门是怎么进的:弹框点了同意,还是公用机免同意。落库是为了事后查得出来
# 「这次谁都没点过同意」,而不是只看到一条 active。
CONSENT_PROMPT = "prompt"
CONSENT_UNATTENDED = "unattended"
ALLOWED_CONSENT_MODES = (CONSENT_PROMPT, CONSENT_UNATTENDED)

# 结束原因。controller_left / agent_kicked 分开记,因为「谁先挂的」在扯皮时是关键。
END_CONTROLLER_LEFT = "controller_left"
END_AGENT_KICKED = "agent_kicked"
END_TIMEOUT = "timeout"
END_MAX_DURATION = "max_duration"
END_CONNECTION_LOST = "connection_lost"
# 同意了,但两端始终没把通路建起来(信令没送到 / 打洞和中转都不通)
END_HANDSHAKE_FAILED = "handshake_failed"

SIGNAL_FROM_CONTROLLER = "controller"
SIGNAL_FROM_AGENT = "agent"
ALLOWED_SIGNAL_SENDERS = (SIGNAL_FROM_CONTROLLER, SIGNAL_FROM_AGENT)

SIGNAL_OFFER = "offer"
SIGNAL_ANSWER = "answer"
SIGNAL_ICE = "ice"
ALLOWED_SIGNAL_KINDS = (SIGNAL_OFFER, SIGNAL_ANSWER, SIGNAL_ICE)

# ---------------------------------------------------------------------------
# 上限(对外承诺必须配机制,机制就在这里,不散落在各处魔法数字里)
# ---------------------------------------------------------------------------
# 同意框弹出后没人理,多久自动当拒绝处理
CONSENT_TIMEOUT_SECONDS = 60
# 同意之后多久画面还没通,就判握手失败、把被控机放出来。不收的话这条会话会以
# 「已同意」占住被控机两个小时,期间谁都连不上它(2026-09-18 真机首测就卡在这)
HANDSHAKE_TIMEOUT_SECONDS = 90
# 单场会话最长时间,到点强制结束
SESSION_MAX_SECONDS = 2 * 60 * 60
# 一台公用机最多放行多少人免同意
MAX_UNATTENDED_GRANTS = 10
# 一台中转节点同时最多扛几路
MAX_CONCURRENT_RELAY_PER_NODE = 5
# TURN 凭据有效期
TURN_CREDENTIAL_TTL_SECONDS = 600
# 被控端心跳超过这个时间没来,就当它离线(列表里显示灰的,连不了)
DEVICE_ONLINE_WINDOW_SECONDS = 90


class RdDevice(Base):
    """一台能被远程操控的机器。

    ``device_uuid`` 复用客户端已有的设备 UUID,所以这张表的行是被控端自己登记
    上来的,不是人手建的。
    """

    __tablename__ = "rd_devices"
    __table_args__ = (
        UniqueConstraint("device_uuid", name="uq_rd_devices_device_uuid"),
        Index("ix_rd_devices_owner", "owner_user_id"),
        Index("ix_rd_devices_last_seen", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # 「公用机」:车间那种没人守着的机器。标记动作必须在那台机器上原生确认过一次,
    # 服务端只认已确认的结果(见 service.mark_unattended),防止有人远程把别人的
    # 私人电脑偷偷标成公用机。
    is_unattended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    unattended_marked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    unattended_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RdUnattendedGrant(Base):
    """公用机的免同意名单:谁可以不弹框直接进这台机器。"""

    __tablename__ = "rd_unattended_grants"
    __table_args__ = (
        UniqueConstraint(
            "device_id", "grantee_user_id", name="uq_rd_unattended_grants_pair"
        ),
        Index("ix_rd_unattended_grants_grantee", "grantee_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("rd_devices.id", ondelete="CASCADE"), nullable=False
    )
    grantee_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RdSession(Base):
    """一次远程操控的完整台账。只增不删。"""

    __tablename__ = "rd_sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('requested', 'consented', 'active', 'denied', 'expired', 'ended')",
            name=conv("ck_rd_sessions_state"),
        ),
        CheckConstraint(
            "consent_mode IN ('prompt', 'unattended')",
            name=conv("ck_rd_sessions_consent_mode"),
        ),
        Index("ix_rd_sessions_device_state", "device_id", "state"),
        Index("ix_rd_sessions_controller", "controller_user_id"),
        Index("ix_rd_sessions_requested_at", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("rd_devices.id", ondelete="CASCADE"), nullable=False
    )
    controller_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    consent_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    device: Mapped["RdDevice"] = relationship(lazy="selectin")


class RdSignal(Base):
    """WebRTC 握手期间两边互递的信封。

    主键用自增整数而不是 UUID:两边都是「拿上次读到的 id 往后要」,自增列天然给
    出顺序和游标。建连完成后这些行就没用了,由 service 按会话清掉。
    """

    __tablename__ = "rd_signals"
    __table_args__ = (
        CheckConstraint(
            "sender IN ('controller', 'agent')", name=conv("ck_rd_signals_sender")
        ),
        CheckConstraint(
            "kind IN ('offer', 'answer', 'ice')", name=conv("ck_rd_signals_kind")
        ),
        Index("ix_rd_signals_session_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("rd_sessions.id", ondelete="CASCADE"), nullable=False
    )
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# 客户端诊断:一次上报最多几条、留多久、一个人一小时最多收多少(防失控的页面刷爆库)
TRACE_MAX_ENTRIES_PER_POST = 200
TRACE_RETENTION_DAYS = 14
TRACE_MAX_PER_USER_PER_HOUR = 3000


class RdClientTrace(Base):
    """两端页面逐步记下来的建连过程,事后补传。

    2026-09-18 真机首测:发起端同意后再没有请求到达服务器,服务器侧看不到它卡在哪。
    这张表就是本机那一侧的黑匣子——页面每走一步先记在本地,网络恢复/下次打开时再
    传上来。``(client_id, seq)`` 唯一:补传重试不会重复入库。

    只记步骤、耗时、错误名和状态,**不记 SDP、不记候选地址**。
    """

    __tablename__ = "rd_client_traces"
    __table_args__ = (
        UniqueConstraint("client_id", "seq", name="uq_rd_client_traces_client_seq"),
        Index("ix_rd_client_traces_session", "session_id", "client_at"),
        Index("ix_rd_client_traces_user_received", "user_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 每次打开页面随机生成一个;同一个人开两个窗口也分得开
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_label: Mapped[str] = mapped_column(String(120), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # 不挂外键:会话被清掉了,黑匣子也得留着
    session_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    step: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    client_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
