"""RD 系列 · 远程桌面的请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SessionState = Literal[
    "requested", "consented", "active", "denied", "expired", "ended"
]
ConsentMode = Literal["prompt", "unattended"]
SignalKind = Literal["offer", "answer", "ice"]

# 设备 UUID 用客户端已有的那一个,格式跟 VPN 侧保持一致
DEVICE_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
AGENT_VERSION_PATTERN = r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:-[0-9A-Za-z.-]{1,32})?$"


class DeviceRegister(BaseModel):
    device_uuid: str = Field(pattern=DEVICE_UUID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=32)
    agent_version: str = Field(pattern=AGENT_VERSION_PATTERN)


class DeviceHeartbeat(BaseModel):
    agent_version: str | None = Field(default=None, pattern=AGENT_VERSION_PATTERN)


class GrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grantee_user_id: int
    grantee_name: str | None = None
    created_at: datetime


class DeviceRead(BaseModel):
    id: UUID
    name: str
    platform: str
    agent_version: str
    owner_user_id: int
    owner_name: str | None = None
    is_online: bool
    is_mine: bool
    is_unattended: bool
    # 这个人连这台机器要不要弹框。前端据此把按钮文案写成「请求控制」还是「直接连接」
    needs_consent: bool
    # 这台机器上现在有没有别人在连
    busy: bool
    last_seen_at: datetime | None = None


class DeviceDetail(DeviceRead):
    grants: list[GrantRead] = Field(default_factory=list)


class UnattendedMark(BaseModel):
    enabled: bool
    # 由被控端主进程在本机弹原生框拿到「是」之后才带上来
    confirmed_on_device: bool = False


class GrantCreate(BaseModel):
    grantee_user_id: int


class SessionRead(BaseModel):
    id: UUID
    device_id: UUID
    device_name: str | None = None
    controller_user_id: int
    controller_name: str | None = None
    state: SessionState
    consent_mode: ConsentMode
    requested_at: datetime
    responded_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None


class SessionCreate(BaseModel):
    device_id: UUID


class SessionRespond(BaseModel):
    approve: bool


class SessionEnd(BaseModel):
    reason: Literal[
        "controller_left", "agent_kicked", "connection_lost"
    ] = "controller_left"


class SignalPush(BaseModel):
    kind: SignalKind
    # SDP 可以很长,ICE candidate 很短;给一个宽松但有限的上限
    payload: str = Field(min_length=1, max_length=64_000)


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: SignalKind
    payload: str


class IceServers(BaseModel):
    """给浏览器 RTCPeerConnection 直接用的通路配置。"""

    stun_urls: list[str] = Field(default_factory=list)
    turn_urls: list[str] = Field(default_factory=list)
    turn_username: str | None = None
    turn_credential: str | None = None
    ttl: int = 0


class TraceEntry(BaseModel):
    """页面记下的一步。字段都截短限长:黑匣子不该变成能塞任意数据的口子。"""

    client_id: str = Field(pattern=r"^[0-9a-f-]{8,36}$")
    client_label: str = Field(default="", max_length=120)
    seq: int = Field(ge=0, le=2_000_000_000)
    at: datetime
    step: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9_.:-]+$")
    session_id: UUID | None = None
    detail: str = Field(default="", max_length=1000)


class TracePush(BaseModel):
    entries: list[TraceEntry] = Field(min_length=1, max_length=200)


class TraceAck(BaseModel):
    accepted: int
    # 这批里客户端可以从本地删掉的(已入库或本来就重复的)
    stored: int
