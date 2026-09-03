"""n8n 串行派单队列的**行为**契约。

为什么单开一份：这套队列在 5 个模块里各有一份实现（P 上架、GEO 发布、
GEO 反链、SEO 发布、B2B 小窗），而在这之前关于它的全部断言都是
`inspect.getsource()` + 字符串包含 —— 断的是**源码文本**，不是行为。

源码断言在这里格外危险：它一方面挡不住真正的回归（把 `db.commit()` 挪到
`post_to_n8n` 之后但换个写法，断言照样绿），另一方面又会因为纯粹的重构
（比如把五份合成一份）而全部变红，逼着人去改测试而不是去验行为。

下面六条是这套队列真正要保住的东西，全部**真跑**：
  1. 失联收尸：dispatched 超时的标 failed，把跑道腾出来
  2. 严格串行：有 in-flight 就不派新单
  3. 先提交再发送（2026-07-23 实锤的竞态：n8n 毫秒级回来取包，
     行没落库会按「token 无效」401 打回）
  4. 发送失败不阻塞队列：本单标 failed，继续踢下一单
  5. 终态幂等：n8n 重试不能把 success 改成 failed
  6. 行锁 skip_locked：并发触发点不会重复派同一单

以 P 的上架队列为样本 —— 它是这五份里唯一带特殊逻辑的（见 record_result
里「迟到的 success 可以翻案已被看门狗误判为 failed 的单」），也是最要紧的一条链。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from backend.app.db.session import SessionLocal
from backend.app.modules.p_series.upload import jobs as p_jobs
from backend.app.services import n8n_dispatch
from backend.app.modules.p_series.upload.models import PUploadJob

PUBLIC_BASE = "https://ops.example.test"


def _make_job(db, *, status: str, created_shift_seconds: int = 0, **kwargs) -> PUploadJob:
    now = datetime.now(UTC)
    job = PUploadJob(
        job_id=f"test-{uuid.uuid4().hex[:12]}",
        product_id=uuid.uuid4(),
        channel="woocommerce",
        status=status,
        token=uuid.uuid4().hex,
        created_at=now + timedelta(seconds=created_shift_seconds),
        **kwargs,
    )
    db.add(job)
    db.flush()
    return job


@pytest.fixture
def db():
    with SessionLocal() as session:
        # 这张表只有本文件建的行（job_id 带 test- 前缀），跑完清干净。
        yield session
        session.rollback()
        session.execute(delete(PUploadJob).where(PUploadJob.job_id.like("test-%")))
        session.commit()


def _clear(db) -> None:
    db.execute(delete(PUploadJob))
    db.commit()


def test_stale_dispatched_jobs_are_reaped_and_free_the_runway(db, monkeypatch) -> None:
    """看门狗：dispatched 超时的标 failed —— 否则一单卡死整条队列。"""
    _clear(db)
    sent: list[str] = []
    monkeypatch.setattr(
        n8n_dispatch,
        "post_to_n8n",
        lambda env, payload, **_: sent.append(payload["job_id"]),
    )

    overdue = datetime.now(UTC) - timedelta(
        minutes=p_jobs.IN_FLIGHT_TIMEOUT_MINUTES + 1
    )
    stale = _make_job(db, status="dispatched", dispatched_at=overdue)
    waiting = _make_job(db, status="queued", created_shift_seconds=1)
    db.commit()

    released = p_jobs.kick_queue(db, public_base=PUBLIC_BASE)

    db.refresh(stale)
    assert stale.status == "failed"
    assert stale.finished_at is not None
    assert "未回传" in (stale.error or "")
    # 跑道腾出来了，排队的那单当场就派出去
    assert released is not None and released.job_id == waiting.job_id
    assert sent == [waiting.job_id]


def test_in_flight_job_blocks_new_dispatch(db, monkeypatch) -> None:
    """严格串行：还有 in-flight 就一单都不派。"""
    _clear(db)
    sent: list[str] = []
    monkeypatch.setattr(
        n8n_dispatch,
        "post_to_n8n",
        lambda env, payload, **_: sent.append(payload["job_id"]),
    )

    _make_job(db, status="dispatched", dispatched_at=datetime.now(UTC))
    _make_job(db, status="queued", created_shift_seconds=1)
    db.commit()

    assert p_jobs.kick_queue(db, public_base=PUBLIC_BASE) is None
    assert sent == []


def test_job_row_is_committed_before_the_webhook_fires(db, monkeypatch) -> None:
    """**2026-07-23 竞态**：n8n 收到 webhook 后毫秒级回来取包。

    任务行若还没提交，取数会按「token 无效」401 打回，整单白跑。
    所以派单必须先把 dispatched 落库成既成事实，再发 webhook。

    这里用另开一个会话去查来证明「已提交」—— 同一个会话里看得见的是
    未提交的脏数据，证明不了任何事。
    """
    _clear(db)
    seen_from_another_session: list[str | None] = []

    sent_payloads: list[dict] = []

    def _capture(env, payload, **_):
        del env
        sent_payloads.append(payload)
        with SessionLocal() as probe:
            seen_from_another_session.append(
                probe.scalar(
                    select(PUploadJob.status).where(
                        PUploadJob.job_id == payload["job_id"]
                    )
                )
            )

    monkeypatch.setattr(n8n_dispatch, "post_to_n8n", _capture)
    queued = _make_job(db, status="queued")
    db.commit()

    p_jobs.kick_queue(db, public_base=PUBLIC_BASE)

    assert seen_from_another_session == ["dispatched"], (
        "webhook 发出去的时候，别的会话还看不到 dispatched —— "
        "n8n 回来取包会 401"
    )
    # 顺带钉住载荷形状：收口前测试打在模块内部的 `_send_to_n8n` 上，
    # 整个载荷被替换掉，这几个字段一个都验不到 —— 而 n8n 那头正是靠它们
    # 取包和回调，拼错了整单静默失败。
    (payload,) = sent_payloads
    assert payload["job_id"] == queued.job_id
    assert payload["token"] == queued.token
    assert f"/p/products/{queued.product_id}/upload-package" in payload["package_url"]
    assert payload["callback_url"].endswith(f"/p/uploads/{queued.job_id}/result")


def test_dispatch_failure_fails_that_job_and_keeps_the_queue_moving(db, monkeypatch):
    """一个坏 webhook 不能把整条队列卡死：本单标 failed，继续踢下一单。"""
    _clear(db)
    first = _make_job(db, status="queued")
    second = _make_job(db, status="queued", created_shift_seconds=1)
    db.commit()

    attempted: list[str] = []

    def _fail_first(env, payload, **_):
        del env
        attempted.append(payload["job_id"])
        if payload["job_id"] == first.job_id:
            raise RuntimeError("webhook 挂了")

    monkeypatch.setattr(n8n_dispatch, "post_to_n8n", _fail_first)

    released = p_jobs.kick_queue(db, public_base=PUBLIC_BASE)

    db.refresh(first)
    assert first.status == "failed"
    assert "dispatch failed" in (first.error or "")
    assert released is not None and released.job_id == second.job_id
    assert attempted == [first.job_id, second.job_id]


def _report(db, job, status, *, error=None, external_product_id=None):
    return p_jobs.record_result(
        db,
        job_id=job.job_id,
        token=job.token,
        status=status,
        external_product_id=external_product_id,
        external_url=None,
        error=error,
    )


def test_success_is_terminal_and_cannot_be_downgraded(db) -> None:
    """n8n 重试不该把已经成功的一单改成失败。"""
    _clear(db)
    job = _make_job(db, status="dispatched", dispatched_at=datetime.now(UTC))
    db.commit()

    _report(db, job, "success")
    db.refresh(job)
    assert job.status == "success"

    _report(db, job, "failed", error="迟到的失败回报")
    db.refresh(job)
    assert job.status == "success", "终态被覆盖了"


def test_a_real_failure_is_terminal_too(db) -> None:
    """n8n **明确报错**（事实）之后，迟到的成功不该翻案。"""
    _clear(db)
    job = _make_job(db, status="dispatched", dispatched_at=datetime.now(UTC))
    db.commit()

    _report(db, job, "failed", error="Woo 拒绝：SKU 重复")
    db.refresh(job)
    assert job.status == "failed"

    _report(db, job, "success", external_product_id="4394")
    db.refresh(job)
    assert job.status == "failed", "n8n 明确报的错被翻案了"


def test_late_success_overturns_a_watchdog_guess(db) -> None:
    """**唯一的例外，也是这个模块最要紧的一条语义。**

    failed 有两种来源：n8n 明确报错（事实），和看门狗「超时未回传」（推测）。
    2026-08-11 实测过一次推测错杀：产品其实已经建进 Woo（草稿 4394），
    只是 n8n 的回报节点被跳过，15 分钟后被判失联；人工补回报却被幂等挡住，
    账面永远是「失败」而站上明明有货。**事实必须能覆盖推测。**

    这条语义在 2026-09-03 之前零测试覆盖 —— 唯一提到它的是源码里的一段注释。
    """
    _clear(db)
    job = _make_job(db, status="dispatched", dispatched_at=datetime.now(UTC))
    db.commit()

    # 看门狗收尸（推测），错误文案里带「未回传」
    _report(db, job, "failed", error="n8n 超过 15 分钟未回传，按失联处理")
    db.refresh(job)
    assert job.status == "failed"

    # 人工补回报：事实覆盖推测
    _report(db, job, "success", external_product_id="4394")
    db.refresh(job)
    assert job.status == "success", "看门狗的推测挡住了真实结果，账面对不上"
    assert job.external_product_id == "4394"


def test_row_lock_uses_skip_locked(db) -> None:
    """行锁必须带 skip_locked：两个触发点同时踢队列时，第二个跳过被锁的行，
    而不是排队干等 —— 后者会把 HTTP 请求卡在锁上。

    这条查的是真实发出的 SQL，不是源码文本。
    """
    _clear(db)
    _make_job(db, status="queued")
    db.commit()

    statements: list[str] = []
    from sqlalchemy import event

    def _record(conn, cursor, statement, params, context, executemany):
        del conn, cursor, params, context, executemany
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", _record)
    try:
        p_jobs.kick_queue(db, public_base=PUBLIC_BASE)
    except Exception:  # noqa: BLE001 - 发送会失败，这里只关心 SQL
        pass
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", _record)

    locking = [s for s in statements if "FOR UPDATE" in s.upper()]
    assert locking, "取队列时没有加行锁"
    assert any("SKIP LOCKED" in s.upper() for s in locking), (
        "行锁没带 SKIP LOCKED —— 并发触发点会互相干等"
    )
