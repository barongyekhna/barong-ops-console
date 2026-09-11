"""RD 系列 · 远程桌面的业务逻辑。

这里管四件事:谁能看见哪些机器、这次进门要不要弹框、会话状态机怎么走、TURN 中转
凭据怎么签。

**「要不要弹框」是本模块唯一真正重要的判断**,只有两种情况免弹框:

1. 你连你自己的机器(``device.owner_user_id == user.id``)——两台都是你的,没有
   「别人」需要同意;
2. 那台机器被标成了公用机,**而且**你在它的免同意名单里。

其余一律弹框,而且弹的是被控端的**原生**框(Electron 主进程 ``dialog``),不是网页
弹窗——网页弹窗能被脚本自动点掉,原生框不能。服务端这边只负责记录「这次是怎么进
的」(``consent_mode``),真正的门在被控机本地。

过期清理不靠定时任务:``sweep_stale`` 挂在每个读路径的开头,谁来看一眼就顺手把超
时的收掉。少一个会挂的后台进程,就少一个「容器 Up 但没在干活」的坑。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...models.user import User
from .models import (
    ALLOWED_SIGNAL_KINDS,
    CONSENT_PROMPT,
    CONSENT_UNATTENDED,
    CONSENT_TIMEOUT_SECONDS,
    DEVICE_ONLINE_WINDOW_SECONDS,
    END_MAX_DURATION,
    END_TIMEOUT,
    LIVE_STATES,
    MAX_CONCURRENT_RELAY_PER_NODE,
    MAX_UNATTENDED_GRANTS,
    SESSION_MAX_SECONDS,
    SIGNAL_FROM_AGENT,
    SIGNAL_FROM_CONTROLLER,
    STATE_ACTIVE,
    STATE_CONSENTED,
    STATE_DENIED,
    STATE_ENDED,
    STATE_EXPIRED,
    STATE_REQUESTED,
    TURN_CREDENTIAL_TTL_SECONDS,
    RdDevice,
    RdSession,
    RdSignal,
    RdUnattendedGrant,
)


class RdError(Exception):
    """业务规则不通过。``status`` 直接给 HTTP 层用。"""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 回来的 datetime 不带时区,统一补成 UTC 再比较。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# 设备
# ---------------------------------------------------------------------------
def register_device(
    db: Session,
    *,
    user: User,
    device_uuid: str,
    name: str,
    platform: str,
    agent_version: str,
) -> RdDevice:
    """被控端自己登记上来。同一个 device_uuid 重复登记就是更新。

    归属认「最后在这台机器上登录的人」:机器转手给别人用了,归属就跟着走,原主人
    也就自然失去了对它的免同意特权。这是对的——机器归谁,看谁在用。
    """
    device = db.scalar(
        select(RdDevice).where(RdDevice.device_uuid == device_uuid)
    )
    if device is None:
        device = RdDevice(
            device_uuid=device_uuid,
            owner_user_id=user.id,
            name=name,
            platform=platform,
            agent_version=agent_version,
            last_seen_at=_now(),
        )
        db.add(device)
    else:
        if device.owner_user_id != user.id:
            # 换人了:归属转移,同时清掉旧主人留下的免同意名单和公用机标记,
            # 免得新主人的机器上还挂着上一任批准过的人。
            device.owner_user_id = user.id
            device.is_unattended = False
            device.unattended_marked_by = None
            device.unattended_marked_at = None
            db.query(RdUnattendedGrant).filter(
                RdUnattendedGrant.device_id == device.id
            ).delete(synchronize_session=False)
        device.name = name
        device.platform = platform
        device.agent_version = agent_version
        device.last_seen_at = _now()
    db.flush()
    return device


def touch_device(db: Session, *, device: RdDevice, agent_version: str | None = None) -> None:
    """心跳。列表里的在线灯只认这个时间戳。"""
    device.last_seen_at = _now()
    if agent_version:
        device.agent_version = agent_version
    db.flush()


def device_is_online(device: RdDevice, *, now: datetime | None = None) -> bool:
    seen = _aware(device.last_seen_at)
    if seen is None:
        return False
    return (now or _now()) - seen <= timedelta(seconds=DEVICE_ONLINE_WINDOW_SECONDS)


def get_device(db: Session, device_id: UUID) -> RdDevice:
    device = db.get(RdDevice, device_id)
    if device is None:
        raise RdError(404, "这台设备不存在,可能已经被移除。")
    return device


def list_devices(db: Session, *, user: User) -> list[RdDevice]:
    """所有人都看得见所有机器——这个模块按设计就是全员互通的。

    看得见不等于进得去:能不能进、要不要弹框,由 ``decide_consent_mode`` 说了算。
    """
    return list(
        db.scalars(
            select(RdDevice).order_by(
                RdDevice.last_seen_at.desc().nullslast(), RdDevice.name
            )
        )
    )


def user_has_unattended_grant(db: Session, *, device: RdDevice, user: User) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(RdUnattendedGrant)
            .where(
                RdUnattendedGrant.device_id == device.id,
                RdUnattendedGrant.grantee_user_id == user.id,
            )
        )
        or 0
    ) > 0


def decide_consent_mode(db: Session, *, device: RdDevice, user: User) -> str:
    """这次进门要不要弹框。整个模块最要紧的一行判断。"""
    if device.owner_user_id == user.id:
        return CONSENT_UNATTENDED
    if device.is_unattended and user_has_unattended_grant(db, device=device, user=user):
        return CONSENT_UNATTENDED
    return CONSENT_PROMPT


# ---------------------------------------------------------------------------
# 公用机
# ---------------------------------------------------------------------------
def mark_unattended(
    db: Session,
    *,
    user: User,
    device: RdDevice,
    enabled: bool,
    confirmed_on_device: bool,
) -> RdDevice:
    """把一台机器标成 / 取消公用机。

    两道门:调用人必须是这台机器的归属人,而且 ``confirmed_on_device`` 必须为真
    ——那个标志由被控端 Electron 主进程在**本机弹出原生确认框**并拿到「是」之后
    才会带上来。

    诚实说明这道门的边界:``confirmed_on_device`` 是客户端自称的,服务端无法密码
    学地证明那个框真的弹过。真正扛事的是另外两条——只有归属人能改,而归属人就是
    此刻正登录在那台机器上的人。远程的第三方拿不到这个组合。
    """
    if device.owner_user_id != user.id:
        raise RdError(403, "只有这台机器的归属人才能改它的公用机设置。")
    if enabled and not confirmed_on_device:
        raise RdError(400, "标记公用机必须先在那台机器上确认一次。")
    device.is_unattended = enabled
    if enabled:
        device.unattended_marked_by = user.id
        device.unattended_marked_at = _now()
    else:
        device.unattended_marked_by = None
        device.unattended_marked_at = None
        db.query(RdUnattendedGrant).filter(
            RdUnattendedGrant.device_id == device.id
        ).delete(synchronize_session=False)
    db.flush()
    return device


def grant_unattended(
    db: Session, *, user: User, device: RdDevice, grantee_user_id: int
) -> RdUnattendedGrant:
    if device.owner_user_id != user.id:
        raise RdError(403, "只有这台机器的归属人才能改免同意名单。")
    if not device.is_unattended:
        raise RdError(400, "这台机器还不是公用机,先标记成公用机再加名单。")
    if grantee_user_id == device.owner_user_id:
        raise RdError(400, "归属人本来就不用同意,不必加进名单。")
    if db.get(User, grantee_user_id) is None:
        raise RdError(404, "这个用户不存在。")
    existing = db.scalar(
        select(RdUnattendedGrant).where(
            RdUnattendedGrant.device_id == device.id,
            RdUnattendedGrant.grantee_user_id == grantee_user_id,
        )
    )
    if existing is not None:
        return existing
    count = (
        db.scalar(
            select(func.count())
            .select_from(RdUnattendedGrant)
            .where(RdUnattendedGrant.device_id == device.id)
        )
        or 0
    )
    if count >= MAX_UNATTENDED_GRANTS:
        raise RdError(
            409, f"一台公用机最多放行 {MAX_UNATTENDED_GRANTS} 个人,先删掉几个再加。"
        )
    grant = RdUnattendedGrant(
        device_id=device.id,
        grantee_user_id=grantee_user_id,
        granted_by_user_id=user.id,
    )
    db.add(grant)
    db.flush()
    return grant


def revoke_unattended(
    db: Session, *, user: User, device: RdDevice, grantee_user_id: int
) -> None:
    if device.owner_user_id != user.id:
        raise RdError(403, "只有这台机器的归属人才能改免同意名单。")
    db.query(RdUnattendedGrant).filter(
        RdUnattendedGrant.device_id == device.id,
        RdUnattendedGrant.grantee_user_id == grantee_user_id,
    ).delete(synchronize_session=False)
    db.flush()


def list_grants(db: Session, *, device: RdDevice) -> list[RdUnattendedGrant]:
    return list(
        db.scalars(
            select(RdUnattendedGrant)
            .where(RdUnattendedGrant.device_id == device.id)
            .order_by(RdUnattendedGrant.created_at)
        )
    )


# ---------------------------------------------------------------------------
# 会话状态机
# ---------------------------------------------------------------------------
def sweep_stale(db: Session) -> None:
    """把超时的会话收掉。挂在读路径开头,不依赖任何后台进程。"""
    now = _now()
    db.execute(
        update(RdSession)
        .where(
            RdSession.state == STATE_REQUESTED,
            RdSession.requested_at
            < now - timedelta(seconds=CONSENT_TIMEOUT_SECONDS),
        )
        .values(state=STATE_EXPIRED, responded_at=now, ended_at=now,
                end_reason=END_TIMEOUT)
    )
    db.execute(
        update(RdSession)
        .where(
            RdSession.state.in_((STATE_CONSENTED, STATE_ACTIVE)),
            RdSession.requested_at < now - timedelta(seconds=SESSION_MAX_SECONDS),
        )
        .values(state=STATE_ENDED, ended_at=now, end_reason=END_MAX_DURATION)
    )
    db.flush()


def live_session_for_device(db: Session, device_id: UUID) -> RdSession | None:
    return db.scalar(
        select(RdSession)
        .where(RdSession.device_id == device_id, RdSession.state.in_(LIVE_STATES))
        .order_by(RdSession.requested_at.desc())
    )


def _active_session_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(RdSession)
            .where(RdSession.state.in_((STATE_CONSENTED, STATE_ACTIVE)))
        )
        or 0
    )


def request_session(db: Session, *, user: User, device_id: UUID) -> RdSession:
    """发起一次操控请求。"""
    sweep_stale(db)
    device = get_device(db, device_id)
    if not device_is_online(device):
        raise RdError(409, "这台机器现在不在线,连不上。")
    if live_session_for_device(db, device.id) is not None:
        raise RdError(409, "这台机器上已经有一个远程会话了,等它结束再来。")

    capacity = MAX_CONCURRENT_RELAY_PER_NODE * max(len(_turn_urls()), 1)
    if _active_session_count(db) >= capacity:
        raise RdError(503, "同时进行的远程会话已达上限,稍后再试。")

    consent_mode = decide_consent_mode(db, device=device, user=user)
    now = _now()
    session = RdSession(
        device_id=device.id,
        controller_user_id=user.id,
        consent_mode=consent_mode,
        # 免同意的直接进 consented,不必在 requested 上空转一圈
        state=STATE_CONSENTED if consent_mode == CONSENT_UNATTENDED else STATE_REQUESTED,
        requested_at=now,
        responded_at=now if consent_mode == CONSENT_UNATTENDED else None,
    )
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, session_id: UUID) -> RdSession:
    session = db.get(RdSession, session_id)
    if session is None:
        raise RdError(404, "这个会话不存在。")
    return session


def _assert_party(session: RdSession, user: User) -> str:
    """当事人才能动这个会话。返回这个人是哪一方。"""
    if session.controller_user_id == user.id:
        return SIGNAL_FROM_CONTROLLER
    if session.device.owner_user_id == user.id:
        return SIGNAL_FROM_AGENT
    raise RdError(403, "你不是这个会话的当事人。")


def respond_session(
    db: Session, *, user: User, session_id: UUID, approve: bool
) -> RdSession:
    """被控端应答同意框。只有被控机的归属人能答。"""
    sweep_stale(db)
    session = get_session(db, session_id)
    if session.device.owner_user_id != user.id:
        raise RdError(403, "只有被控机的归属人能回应这个请求。")
    if session.state != STATE_REQUESTED:
        raise RdError(409, "这个请求已经不在等待回应的状态了。")
    now = _now()
    session.state = STATE_CONSENTED if approve else STATE_DENIED
    session.responded_at = now
    if not approve:
        session.ended_at = now
        session.end_reason = "denied"
    db.flush()
    return session


def activate_session(db: Session, *, user: User, session_id: UUID) -> RdSession:
    """画面真的通了。台账上的「开始时间」以这一刻为准,不是发起那一刻。"""
    session = get_session(db, session_id)
    _assert_party(session, user)
    if session.state == STATE_ACTIVE:
        return session
    if session.state != STATE_CONSENTED:
        raise RdError(409, "这个会话还没被同意,或者已经结束了。")
    session.state = STATE_ACTIVE
    session.started_at = _now()
    db.flush()
    return session


def end_session(
    db: Session, *, user: User, session_id: UUID, reason: str
) -> RdSession:
    """任何一方都能随时结束。"""
    session = get_session(db, session_id)
    _assert_party(session, user)
    if session.state in (STATE_DENIED, STATE_EXPIRED, STATE_ENDED):
        return session
    now = _now()
    session.state = STATE_ENDED
    session.ended_at = now
    session.end_reason = reason
    db.query(RdSignal).filter(RdSignal.session_id == session.id).delete(
        synchronize_session=False
    )
    db.flush()
    return session


def list_sessions(db: Session, *, limit: int = 100) -> list[RdSession]:
    """台账。所有人都看得见——谁连过谁本来就该是公开的。"""
    sweep_stale(db)
    return list(
        db.scalars(
            select(RdSession).order_by(RdSession.requested_at.desc()).limit(limit)
        )
    )


def sessions_for_party(db: Session, *, user: User) -> list[RdSession]:
    """这个人作为任一方参与的、还没进终态的会话。

    SSE 流靠它同时照顾两个身份:我发起去控别人(controller),和别人来控我的机器
    (agent)。两种身份可能同时成立,所以是 OR 不是二选一。
    """
    return list(
        db.scalars(
            select(RdSession)
            .join(RdDevice, RdDevice.id == RdSession.device_id)
            .where(
                RdSession.state.in_(LIVE_STATES),
                (RdSession.controller_user_id == user.id)
                | (RdDevice.owner_user_id == user.id),
            )
            .order_by(RdSession.requested_at)
        )
    )


def pending_requests_for_owner(db: Session, *, user: User) -> list[RdSession]:
    """要在这个人的机器上弹框的请求。被控端 SSE 就是拉这个。"""
    sweep_stale(db)
    return list(
        db.scalars(
            select(RdSession)
            .join(RdDevice, RdDevice.id == RdSession.device_id)
            .where(
                RdDevice.owner_user_id == user.id,
                RdSession.state == STATE_REQUESTED,
            )
            .order_by(RdSession.requested_at)
        )
    )


# ---------------------------------------------------------------------------
# WebRTC 信令中转
# ---------------------------------------------------------------------------
def push_signal(
    db: Session, *, user: User, session_id: UUID, kind: str, payload: str
) -> RdSignal:
    session = get_session(db, session_id)
    sender = _assert_party(session, user)
    if session.state not in (STATE_CONSENTED, STATE_ACTIVE):
        raise RdError(409, "这个会话不在可以建连的状态。")
    if kind not in ALLOWED_SIGNAL_KINDS:
        raise RdError(400, "信令类型不认识。")
    signal = RdSignal(
        session_id=session.id, sender=sender, kind=kind, payload=payload
    )
    db.add(signal)
    db.flush()
    return signal


def pull_signals(
    db: Session, *, user: User, session_id: UUID, after_id: int = 0
) -> list[RdSignal]:
    """只拿对方发的,不回自己的。``after_id`` 是游标。"""
    session = get_session(db, session_id)
    me = _assert_party(session, user)
    peer = SIGNAL_FROM_AGENT if me == SIGNAL_FROM_CONTROLLER else SIGNAL_FROM_CONTROLLER
    return list(
        db.scalars(
            select(RdSignal)
            .where(
                RdSignal.session_id == session.id,
                RdSignal.sender == peer,
                RdSignal.id > after_id,
            )
            .order_by(RdSignal.id)
        )
    )


# ---------------------------------------------------------------------------
# TURN 中转凭据(RFC 5766 短时凭据)
# ---------------------------------------------------------------------------
def _turn_urls() -> list[str]:
    raw = getattr(get_settings(), "rd_turn_urls", None)
    if not raw:
        return []
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def turn_credentials(session_id: UUID) -> dict[str, object]:
    """按会话签一把短时 TURN 凭据。

    绝不把 coturn 的静态口令发给前端——那等于把中转开成公共代理。这里用 RFC 5766
    的短时凭据:用户名是「到期时间戳:会话 id」,口令是用共享密钥对它做的 HMAC,
    coturn 自己就能算出来并校验,过期自动失效。
    """
    urls = _turn_urls()
    secret_obj = getattr(get_settings(), "rd_turn_secret", None)
    if not urls or secret_obj is None:
        # 没配中转就只给 STUN。打得通直连的照样能用,打不通的会失败——这比
        # 假装配好了要诚实。
        return {"urls": [], "username": None, "credential": None, "ttl": 0}
    secret = secret_obj.get_secret_value().encode("utf-8")
    expiry = int(_now().timestamp()) + TURN_CREDENTIAL_TTL_SECONDS
    username = f"{expiry}:{session_id}"
    digest = hmac.new(secret, username.encode("utf-8"), hashlib.sha1).digest()
    return {
        "urls": urls,
        "username": username,
        "credential": base64.b64encode(digest).decode("ascii"),
        "ttl": TURN_CREDENTIAL_TTL_SECONDS,
    }
