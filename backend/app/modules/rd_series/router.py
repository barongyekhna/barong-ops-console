"""RD 系列 · 远程桌面的 HTTP 端点。

**门禁就是「登录」**,没有别的。这个模块按用户拍板不属于任何组织、全员可用,所以
这里只依赖 ``get_current_user``,不挂 ``require_permission`` / ``require_rbac``,
也不碰组织上下文——挂了就会把没有活动组织的人拦在外面,那正好是这里不要的。

看得见 ≠ 进得去:设备列表对所有人开放,但每一条上都带着 ``needs_consent``,真正
的门在被控机本地那个原生同意框,不在这一层。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...core.config import get_settings
from ...core.session_cookies import get_session_id_from_request
from ...db.session import get_db
from ...models.user import User
from . import schemas as S
from . import service
from .models import RdDevice, RdSession
from .stream import rd_stream

router = APIRouter(prefix="/rd", tags=["rd-remote-desktop"])

# 公共 STUN。只用来发现自己的公网地址,不经手任何画面数据。
DEFAULT_STUN_URLS = ("stun:stun.l.google.com:19302",)


def _fail(exc: service.RdError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


def _names(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(User.id, User.username).where(User.id.in_(user_ids))
    ).all()
    return {int(row[0]): row[1] for row in rows}


def _device_read(
    db: Session, *, device: RdDevice, user: User, names: dict[int, str]
) -> S.DeviceRead:
    live = service.live_session_for_device(db, device.id)
    return S.DeviceRead(
        id=device.id,
        name=device.name,
        platform=device.platform,
        agent_version=device.agent_version,
        owner_user_id=device.owner_user_id,
        owner_name=names.get(device.owner_user_id),
        is_online=service.device_is_online(device),
        is_mine=device.owner_user_id == user.id,
        is_unattended=device.is_unattended,
        needs_consent=service.decide_consent_mode(db, device=device, user=user)
        == "prompt",
        busy=live is not None,
        last_seen_at=device.last_seen_at,
    )


def _session_read(
    db: Session, *, session: RdSession, names: dict[int, str]
) -> S.SessionRead:
    return S.SessionRead(
        id=session.id,
        device_id=session.device_id,
        device_name=session.device.name if session.device else None,
        controller_user_id=session.controller_user_id,
        controller_name=names.get(session.controller_user_id),
        state=session.state,
        consent_mode=session.consent_mode,
        requested_at=session.requested_at,
        responded_at=session.responded_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        end_reason=session.end_reason,
    )


# ---------------------------------------------------------------------------
# 设备
# ---------------------------------------------------------------------------
@router.post("/devices/register", response_model=S.DeviceRead)
def register_device(
    payload: S.DeviceRegister,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceRead:
    """被控端自己登记。人手建不了设备,只能是机器自己报上来。"""
    device = service.register_device(
        db,
        user=user,
        device_uuid=payload.device_uuid,
        name=payload.name,
        platform=payload.platform,
        agent_version=payload.agent_version,
    )
    db.commit()
    db.refresh(device)
    return _device_read(
        db, device=device, user=user, names=_names(db, {device.owner_user_id})
    )


@router.post("/devices/{device_id}/heartbeat", response_model=S.DeviceRead)
def heartbeat(
    device_id: UUID,
    payload: S.DeviceHeartbeat,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceRead:
    try:
        device = service.get_device(db, device_id)
    except service.RdError as exc:
        raise _fail(exc) from exc
    if device.owner_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="只有这台机器自己能报心跳。"
        )
    service.touch_device(db, device=device, agent_version=payload.agent_version)
    db.commit()
    db.refresh(device)
    return _device_read(
        db, device=device, user=user, names=_names(db, {device.owner_user_id})
    )


@router.get("/devices", response_model=list[S.DeviceRead])
def list_devices(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[S.DeviceRead]:
    service.sweep_stale(db)
    db.commit()
    devices = service.list_devices(db, user=user)
    names = _names(db, {d.owner_user_id for d in devices})
    return [_device_read(db, device=d, user=user, names=names) for d in devices]


@router.get("/devices/{device_id}", response_model=S.DeviceDetail)
def device_detail(
    device_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceDetail:
    try:
        device = service.get_device(db, device_id)
    except service.RdError as exc:
        raise _fail(exc) from exc
    grants = service.list_grants(db, device=device)
    names = _names(
        db, {device.owner_user_id} | {g.grantee_user_id for g in grants}
    )
    base = _device_read(db, device=device, user=user, names=names)
    return S.DeviceDetail(
        **base.model_dump(),
        grants=[
            S.GrantRead(
                grantee_user_id=g.grantee_user_id,
                grantee_name=names.get(g.grantee_user_id),
                created_at=g.created_at,
            )
            for g in grants
        ],
    )


@router.post("/devices/{device_id}/unattended", response_model=S.DeviceRead)
def set_unattended(
    device_id: UUID,
    payload: S.UnattendedMark,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceRead:
    """标记 / 取消公用机。要求调用人是归属人,且已在那台机器上原生确认过。"""
    try:
        device = service.get_device(db, device_id)
        service.mark_unattended(
            db,
            user=user,
            device=device,
            enabled=payload.enabled,
            confirmed_on_device=payload.confirmed_on_device,
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(device)
    return _device_read(
        db, device=device, user=user, names=_names(db, {device.owner_user_id})
    )


@router.post("/devices/{device_id}/grants", response_model=S.DeviceDetail)
def add_grant(
    device_id: UUID,
    payload: S.GrantCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceDetail:
    try:
        device = service.get_device(db, device_id)
        service.grant_unattended(
            db, user=user, device=device, grantee_user_id=payload.grantee_user_id
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    return device_detail(device_id, db=db, user=user)


@router.delete("/devices/{device_id}/grants/{grantee_user_id}", response_model=S.DeviceDetail)
def remove_grant(
    device_id: UUID,
    grantee_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.DeviceDetail:
    try:
        device = service.get_device(db, device_id)
        service.revoke_unattended(
            db, user=user, device=device, grantee_user_id=grantee_user_id
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    return device_detail(device_id, db=db, user=user)


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
@router.post("/sessions", response_model=S.SessionRead)
def create_session(
    payload: S.SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SessionRead:
    try:
        session = service.request_session(db, user=user, device_id=payload.device_id)
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(session)
    return _session_read(db, session=session, names=_names(db, {user.id}))


@router.get("/sessions/{session_id}", response_model=S.SessionRead)
def session_detail(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SessionRead:
    """单场会话的状态。

    存在的理由是**被控端主进程要自己核实**:免同意的会话不经过原生框,主进程没
    亲手批准过,所以在交出屏幕之前必须自己来问一次后端「这场会话真的成立吗、我
    真的是被控方吗」,而不是听网页说什么就信什么。网页被人塞了脚本的时候,这一
    问就是最后一道拦。
    """
    try:
        session = service.get_session(db, session_id)
        service._assert_party(session, user)
    except service.RdError as exc:
        raise _fail(exc) from exc
    return _session_read(
        db, session=session, names=_names(db, {session.controller_user_id})
    )


@router.post("/sessions/{session_id}/respond", response_model=S.SessionRead)
def respond(
    session_id: UUID,
    payload: S.SessionRespond,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SessionRead:
    """被控端回应同意框。"""
    try:
        session = service.respond_session(
            db, user=user, session_id=session_id, approve=payload.approve
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(session)
    return _session_read(
        db, session=session, names=_names(db, {session.controller_user_id})
    )


@router.post("/sessions/{session_id}/activate", response_model=S.SessionRead)
def activate(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SessionRead:
    """画面真的通了才调这个。台账上的开始时间以这一刻为准。"""
    try:
        session = service.activate_session(db, user=user, session_id=session_id)
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(session)
    return _session_read(
        db, session=session, names=_names(db, {session.controller_user_id})
    )


@router.post("/sessions/{session_id}/end", response_model=S.SessionRead)
def end(
    session_id: UUID,
    payload: S.SessionEnd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SessionRead:
    try:
        session = service.end_session(
            db, user=user, session_id=session_id, reason=payload.reason
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(session)
    return _session_read(
        db, session=session, names=_names(db, {session.controller_user_id})
    )


@router.get("/sessions", response_model=list[S.SessionRead])
def ledger(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[S.SessionRead]:
    """台账。谁连过谁、连了多久,所有人都查得到。"""
    sessions = service.list_sessions(db, limit=limit)
    db.commit()
    names = _names(db, {s.controller_user_id for s in sessions})
    return [_session_read(db, session=s, names=names) for s in sessions]


@router.get("/sessions/{session_id}/ice", response_model=S.IceServers)
def ice_servers(
    session_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.IceServers:
    """这场会话的通路配置。TURN 凭据是按会话签的短时凭据,十分钟就过期。"""
    try:
        session = service.get_session(db, session_id)
        service._assert_party(session, user)
    except service.RdError as exc:
        raise _fail(exc) from exc
    turn = service.turn_credentials(session.id)
    return S.IceServers(
        stun_urls=list(DEFAULT_STUN_URLS),
        turn_urls=list(turn["urls"]),  # type: ignore[arg-type]
        turn_username=turn["username"],  # type: ignore[arg-type]
        turn_credential=turn["credential"],  # type: ignore[arg-type]
        ttl=turn["ttl"],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 信令
# ---------------------------------------------------------------------------
@router.post("/sessions/{session_id}/signals", response_model=S.SignalRead)
def push_signal(
    session_id: UUID,
    payload: S.SignalPush,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> S.SignalRead:
    try:
        signal = service.push_signal(
            db,
            user=user,
            session_id=session_id,
            kind=payload.kind,
            payload=payload.payload,
        )
    except service.RdError as exc:
        raise _fail(exc) from exc
    db.commit()
    db.refresh(signal)
    return S.SignalRead.model_validate(signal)


@router.get("/stream")
def stream(
    request: Request,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """一条 SSE 喂完:有人要连我、会话状态变了、对方递来信令。"""
    session_id = get_session_id_from_request(request, settings=get_settings())
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )
    return StreamingResponse(
        rd_stream(
            request=request, session_id=session_id, actor_user_id=int(user.id)
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
