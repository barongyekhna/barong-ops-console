"""RD 系列 · 远程桌面:同意判定、会话状态机、公用机名单、信令隔离。

这些测试要真数据库(建表由 integration 通道的 alembic upgrade 完成)。

压的重点是**「这次进门要不要弹框」**——整个模块的安全性全压在这一个判断上,所以
它的四种组合(自己的机器 / 别人的机器 / 公用机在名单 / 公用机不在名单)每种都要有
一条测试盯着。
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.rd_series import service
from backend.app.modules.rd_series.models import (
    CONSENT_PROMPT,
    CONSENT_UNATTENDED,
    CONSENT_TIMEOUT_SECONDS,
    HANDSHAKE_TIMEOUT_SECONDS,
    MAX_UNATTENDED_GRANTS,
    STATE_ACTIVE,
    STATE_CONSENTED,
    STATE_DENIED,
    STATE_ENDED,
    STATE_EXPIRED,
    STATE_REQUESTED,
    RdClientTrace,
    RdDevice,
    RdSession,
    RdSignal,
    RdUnattendedGrant,
)

pytestmark = pytest.mark.integration

USERNAMES = ("rd_alice", "rd_bob", "rd_carol")


def _clear(session) -> None:
    for model in (RdClientTrace, RdSignal, RdSession, RdUnattendedGrant, RdDevice):
        session.execute(delete(model))
    session.execute(delete(User).where(User.username.in_(USERNAMES)))
    session.commit()


def _user(session, username: str) -> User:
    user = User(
        username=username, password_hash="x", role="editor", is_active=True
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def db():
    with SessionLocal() as session:
        _clear(session)
        yield session
        _clear(session)


@pytest.fixture
def alice(db) -> User:
    return _user(db, "rd_alice")


@pytest.fixture
def bob(db) -> User:
    return _user(db, "rd_bob")


@pytest.fixture
def carol(db) -> User:
    return _user(db, "rd_carol")


def _register(db, user: User, name: str = "工位机") -> RdDevice:
    return service.register_device(
        db,
        user=user,
        device_uuid=str(uuid4()),
        name=name,
        platform="win32",
        agent_version="0.4.0-pilot",
    )


# ---------------------------------------------------------------------------
# 同意判定:整个模块的安全性都压在这四条上
# ---------------------------------------------------------------------------
def test_own_device_never_prompts(db, alice):
    """连自己的机器不弹框——两台都是你的,没有「别人」需要同意。"""
    device = _register(db, alice)
    assert service.decide_consent_mode(db, device=device, user=alice) == CONSENT_UNATTENDED


def test_someone_elses_device_always_prompts(db, alice, bob):
    """连别人的机器一定弹框。这是默认,而且改不掉。"""
    device = _register(db, alice)
    assert service.decide_consent_mode(db, device=device, user=bob) == CONSENT_PROMPT


def test_unattended_device_with_grant_skips_prompt(db, alice, bob):
    """公用机 + 在名单里 = 免同意。车间那台没人守的机器就靠这个。"""
    device = _register(db, alice, "车间公用机")
    service.mark_unattended(
        db, user=alice, device=device, enabled=True, confirmed_on_device=True
    )
    service.grant_unattended(db, user=alice, device=device, grantee_user_id=bob.id)
    assert service.decide_consent_mode(db, device=device, user=bob) == CONSENT_UNATTENDED


def test_unattended_device_without_grant_still_prompts(db, alice, bob, carol):
    """公用机不等于谁都能进——不在名单里照样弹框。"""
    device = _register(db, alice, "车间公用机")
    service.mark_unattended(
        db, user=alice, device=device, enabled=True, confirmed_on_device=True
    )
    service.grant_unattended(db, user=alice, device=device, grantee_user_id=bob.id)
    assert service.decide_consent_mode(db, device=device, user=carol) == CONSENT_PROMPT


def test_grant_without_unattended_flag_still_prompts(db, alice, bob):
    """取消公用机标记会连名单一起清掉,不留后门。"""
    device = _register(db, alice)
    service.mark_unattended(
        db, user=alice, device=device, enabled=True, confirmed_on_device=True
    )
    service.grant_unattended(db, user=alice, device=device, grantee_user_id=bob.id)
    service.mark_unattended(
        db, user=alice, device=device, enabled=False, confirmed_on_device=True
    )
    assert service.list_grants(db, device=device) == []
    assert service.decide_consent_mode(db, device=device, user=bob) == CONSENT_PROMPT


# ---------------------------------------------------------------------------
# 公用机的两道门
# ---------------------------------------------------------------------------
def test_marking_unattended_requires_on_device_confirmation(db, alice):
    device = _register(db, alice)
    with pytest.raises(service.RdError) as exc:
        service.mark_unattended(
            db, user=alice, device=device, enabled=True, confirmed_on_device=False
        )
    assert exc.value.status == 400


def test_only_owner_can_mark_unattended(db, alice, bob):
    device = _register(db, alice)
    with pytest.raises(service.RdError) as exc:
        service.mark_unattended(
            db, user=bob, device=device, enabled=True, confirmed_on_device=True
        )
    assert exc.value.status == 403


def test_grant_list_is_capped(db, alice):
    device = _register(db, alice)
    service.mark_unattended(
        db, user=alice, device=device, enabled=True, confirmed_on_device=True
    )
    for index in range(MAX_UNATTENDED_GRANTS):
        extra = _user(db, f"rd_filler_{index}")
        service.grant_unattended(
            db, user=alice, device=device, grantee_user_id=extra.id
        )
    overflow = _user(db, "rd_filler_overflow")
    with pytest.raises(service.RdError) as exc:
        service.grant_unattended(
            db, user=alice, device=device, grantee_user_id=overflow.id
        )
    assert exc.value.status == 409
    db.execute(delete(User).where(User.username.like("rd_filler_%")))
    db.commit()


def test_device_handover_wipes_previous_trust(db, alice, bob, carol):
    """机器转手给别人用,旧主人批准过的人立刻失效。"""
    device = _register(db, alice, "转手机")
    service.mark_unattended(
        db, user=alice, device=device, enabled=True, confirmed_on_device=True
    )
    service.grant_unattended(db, user=alice, device=device, grantee_user_id=carol.id)
    assert service.decide_consent_mode(db, device=device, user=carol) == CONSENT_UNATTENDED

    service.register_device(
        db,
        user=bob,
        device_uuid=device.device_uuid,
        name="转手机",
        platform="win32",
        agent_version="0.4.0-pilot",
    )
    db.refresh(device)
    assert device.owner_user_id == bob.id
    assert device.is_unattended is False
    assert service.list_grants(db, device=device) == []
    assert service.decide_consent_mode(db, device=device, user=carol) == CONSENT_PROMPT


# ---------------------------------------------------------------------------
# 会话状态机
# ---------------------------------------------------------------------------
def test_request_against_own_device_is_born_consented(db, alice):
    device = _register(db, alice)
    session = service.request_session(db, user=alice, device_id=device.id)
    assert session.state == STATE_CONSENTED
    assert session.consent_mode == CONSENT_UNATTENDED
    assert session.responded_at is not None


def test_request_against_other_device_waits_for_consent(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    assert session.state == STATE_REQUESTED
    assert session.consent_mode == CONSENT_PROMPT
    assert session.responded_at is None


def test_offline_device_cannot_be_controlled(db, alice, bob):
    device = _register(db, alice)
    device.last_seen_at = service._now() - timedelta(hours=1)
    db.flush()
    with pytest.raises(service.RdError) as exc:
        service.request_session(db, user=bob, device_id=device.id)
    assert exc.value.status == 409


def test_one_live_session_per_device(db, alice, bob, carol):
    device = _register(db, alice)
    service.request_session(db, user=bob, device_id=device.id)
    with pytest.raises(service.RdError) as exc:
        service.request_session(db, user=carol, device_id=device.id)
    assert exc.value.status == 409


def test_only_device_owner_can_respond(db, alice, bob, carol):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    for outsider in (bob, carol):
        with pytest.raises(service.RdError) as exc:
            service.respond_session(
                db, user=outsider, session_id=session.id, approve=True
            )
        assert exc.value.status == 403


def test_denial_is_recorded_and_final(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=False)
    db.refresh(session)
    assert session.state == STATE_DENIED
    assert session.responded_at is not None
    assert session.ended_at is not None
    # 被拒之后不能再改口
    with pytest.raises(service.RdError):
        service.respond_session(db, user=alice, session_id=session.id, approve=True)


def test_activate_stamps_started_at_not_request_time(db, alice, bob):
    """台账上的「开始」是画面通了那一刻,不是点发起那一刻。"""
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    assert session.started_at is None
    service.activate_session(db, user=bob, session_id=session.id)
    db.refresh(session)
    assert session.state == STATE_ACTIVE
    assert session.started_at is not None


def test_either_party_can_end(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    service.activate_session(db, user=bob, session_id=session.id)
    # 被控端一脚踢断
    service.end_session(
        db, user=alice, session_id=session.id, reason="agent_kicked"
    )
    db.refresh(session)
    assert session.ended_at is not None
    assert session.end_reason == "agent_kicked"


def test_outsider_cannot_touch_session(db, alice, bob, carol):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    with pytest.raises(service.RdError) as exc:
        service.end_session(
            db, user=carol, session_id=session.id, reason="controller_left"
        )
    assert exc.value.status == 403


def test_unanswered_request_expires_and_frees_the_device(db, alice, bob, carol):
    """没人点同意框,超时自动当拒绝,机器不能就此被占死。"""
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    session.requested_at = service._now() - timedelta(
        seconds=CONSENT_TIMEOUT_SECONDS + 5
    )
    db.flush()
    service.sweep_stale(db)
    db.refresh(session)
    assert session.state == STATE_EXPIRED
    assert session.end_reason == "timeout"
    # 机器重新可用
    assert service.request_session(db, user=carol, device_id=device.id) is not None


def test_consented_but_never_connected_is_released(db, alice, bob, carol):
    """2026-09-18 真机首测:同意了但 offer 没送到,会话以「已同意」占住被控机。
    握手超时后必须自动收场,机器重新可用。"""
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    session.responded_at = service._now() - timedelta(
        seconds=HANDSHAKE_TIMEOUT_SECONDS + 5
    )
    db.flush()
    service.sweep_stale(db)
    db.refresh(session)
    assert session.state == STATE_ENDED
    assert session.end_reason == "handshake_failed"
    assert service.request_session(db, user=carol, device_id=device.id) is not None


def test_handshake_timeout_never_touches_a_live_picture(db, alice, bob):
    """画面已经通了的会话(started_at 有值)不归握手超时管。"""
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    service.activate_session(db, user=bob, session_id=session.id)
    session.responded_at = service._now() - timedelta(
        seconds=HANDSHAKE_TIMEOUT_SECONDS + 5
    )
    db.flush()
    service.sweep_stale(db)
    db.refresh(session)
    assert session.state == STATE_ACTIVE


def test_handshake_in_progress_is_left_alone(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    service.sweep_stale(db)
    db.refresh(session)
    assert session.state == STATE_CONSENTED


# ---------------------------------------------------------------------------
# 信令隔离
# ---------------------------------------------------------------------------
def test_signals_only_reach_the_peer(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)

    service.push_signal(
        db, user=bob, session_id=session.id, kind="offer", payload="OFFER"
    )
    service.push_signal(
        db, user=alice, session_id=session.id, kind="answer", payload="ANSWER"
    )

    # 被控端只看得到控制端发的
    to_agent = service.pull_signals(db, user=alice, session_id=session.id)
    assert [s.payload for s in to_agent] == ["OFFER"]
    # 控制端只看得到被控端发的
    to_controller = service.pull_signals(db, user=bob, session_id=session.id)
    assert [s.payload for s in to_controller] == ["ANSWER"]


def test_signal_cursor_does_not_replay(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    first = service.push_signal(
        db, user=bob, session_id=session.id, kind="ice", payload="ICE-1"
    )
    service.push_signal(
        db, user=bob, session_id=session.id, kind="ice", payload="ICE-2"
    )
    rest = service.pull_signals(
        db, user=alice, session_id=session.id, after_id=first.id
    )
    assert [s.payload for s in rest] == ["ICE-2"]


def test_ending_a_session_clears_its_signals(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    service.push_signal(
        db, user=bob, session_id=session.id, kind="offer", payload="OFFER"
    )
    service.end_session(
        db, user=bob, session_id=session.id, reason="controller_left"
    )
    remaining = db.query(RdSignal).filter(RdSignal.session_id == session.id).count()
    assert remaining == 0


def test_signals_rejected_outside_negotiation_window(db, alice, bob):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    # 还没同意就想递信封
    with pytest.raises(service.RdError) as exc:
        service.push_signal(
            db, user=bob, session_id=session.id, kind="offer", payload="OFFER"
        )
    assert exc.value.status == 409


# ---------------------------------------------------------------------------
# TURN 凭据
# ---------------------------------------------------------------------------
def test_turn_credentials_are_empty_when_unconfigured(db):
    """没配中转就诚实地给空,不假装配好了。"""
    creds = service.turn_credentials(uuid4())
    assert creds["urls"] == []
    assert creds["username"] is None


def test_turn_credentials_are_short_lived_hmac(db, monkeypatch):
    """签的是 RFC 5766 短时凭据,不是把 coturn 静态口令发给前端。"""
    from pydantic import SecretStr

    from backend.app.core import config as config_module

    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "rd_turn_urls", "turn:1.2.3.4:3478", raising=False)
    monkeypatch.setattr(
        settings, "rd_turn_secret", SecretStr("shared-secret"), raising=False
    )

    session_id = uuid4()
    creds = service.turn_credentials(session_id)
    assert creds["urls"] == ["turn:1.2.3.4:3478"]
    # 用户名形如「到期时间戳:会话 id」,coturn 自己算得出来
    expiry, _, carried = str(creds["username"]).partition(":")
    assert carried == str(session_id)
    assert int(expiry) > 0
    assert creds["ttl"] == 600
    # 口令不是密钥本身
    assert creds["credential"] != "shared-secret"


# ---------------------------------------------------------------------------
# SSE 流:终态要推得出去,重开不重放
# ---------------------------------------------------------------------------
class _FakeRequest:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.client = None

    async def is_disconnected(self) -> bool:
        return False


def _collect_stream(monkeypatch, user, *, after=0, between=None):
    """把一条(缩短了寿命的)流跑完,返回吐出来的 (event, data)。``between`` 在收到第一帧后执行。"""
    import asyncio
    import json as _json
    from types import SimpleNamespace

    from backend.app.modules.rd_series import stream as rd_stream_module

    monkeypatch.setattr(rd_stream_module, "IDLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(rd_stream_module, "BUSY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(rd_stream_module, "STREAM_LIFETIME_SECONDS", 0.5)
    monkeypatch.setattr(
        rd_stream_module,
        "validate_session",
        lambda _db, **_kw: SimpleNamespace(user=_db.get(User, user.id)),
    )
    monkeypatch.setattr(rd_stream_module, "get_audit_context", lambda _r: None)

    async def run():
        out = []
        gen = rd_stream_module.rd_stream(
            request=_FakeRequest(),
            session_id="x",
            actor_user_id=int(user.id),
            resume_after_signal_id=after,
        )
        seen_first = False
        async for chunk in gen:
            if chunk.startswith("retry:"):
                continue
            event = chunk.split("\n")[0].removeprefix("event: ")
            data = _json.loads(chunk.split("\n")[1].removeprefix("data: "))
            out.append((event, data))
            if not seen_first and between is not None:
                seen_first = True
                between()
        return out

    return asyncio.run(run())


def test_stream_tells_the_controller_it_was_denied(db, alice, bob, monkeypatch):
    """被拒 / 结束的会话已经不在「活会话」里,流必须补推一条,否则发起端永远在等。"""
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    db.commit()

    def deny():
        with SessionLocal() as other:
            service.respond_session(
                other, user=other.get(User, alice.id), session_id=session.id,
                approve=False,
            )
            other.commit()

    frames = _collect_stream(monkeypatch, bob, between=deny)
    states = [data["state"] for event, data in frames if event == "session"]
    assert states == ["requested", "denied"]


def test_reopened_stream_does_not_replay_delivered_signals(db, alice, bob, monkeypatch):
    device = _register(db, alice)
    session = service.request_session(db, user=bob, device_id=device.id)
    service.respond_session(db, user=alice, session_id=session.id, approve=True)
    offer = service.push_signal(
        db, user=bob, session_id=session.id, kind="offer", payload="o"
    )
    db.commit()

    fresh = _collect_stream(monkeypatch, alice)
    assert [d["kind"] for e, d in fresh if e == "signal"] == ["offer"]

    resumed = _collect_stream(monkeypatch, alice, after=offer.id)
    assert [e for e, _d in resumed] == ["session"]


# ---------------------------------------------------------------------------
# 客户端黑匣子
# ---------------------------------------------------------------------------
def _trace_entries(client_id: str, seqs, session_id=None):
    return [
        {
            "client_id": client_id,
            "client_label": "client/0.3.0 chrome/150",
            "seq": seq,
            "at": service._now(),
            "step": "ctl.offer_post_fail",
            "session_id": session_id,
            "detail": '{"attempt":1}',
        }
        for seq in seqs
    ]


def test_trace_resend_is_idempotent(db, alice):
    """补传重试是常态:同一 (client_id, seq) 再来一次不能重复入库,但要告诉客户端可以删了。"""
    cid = str(uuid4())
    assert service.store_traces(db, user=alice, entries=_trace_entries(cid, [1, 2, 3])) == (3, 3)
    assert service.store_traces(db, user=alice, entries=_trace_entries(cid, [2, 3, 4])) == (1, 3)
    db.flush()
    assert db.query(RdClientTrace).filter_by(client_id=cid).count() == 4


def test_trace_hourly_cap_refuses_whole_batch(db, alice, monkeypatch):
    monkeypatch.setattr(service, "TRACE_MAX_PER_USER_PER_HOUR", 5)
    cid = str(uuid4())
    assert service.store_traces(db, user=alice, entries=_trace_entries(cid, range(4))) == (4, 4)
    # 再来 2 条就超了:整批拒收,客户端留着以后传
    assert service.store_traces(db, user=alice, entries=_trace_entries(cid, [10, 11])) == (0, 0)


def test_old_traces_are_pruned(db, alice):
    cid = str(uuid4())
    service.store_traces(db, user=alice, entries=_trace_entries(cid, [1]))
    db.flush()
    row = db.query(RdClientTrace).filter_by(client_id=cid).one()
    row.received_at = service._now() - timedelta(days=30)
    db.flush()
    service.store_traces(db, user=alice, entries=_trace_entries(str(uuid4()), [1]))
    db.flush()
    assert db.query(RdClientTrace).filter_by(client_id=cid).count() == 0
