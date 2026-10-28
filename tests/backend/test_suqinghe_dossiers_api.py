"""苏青禾 1688 → K 档案:排队、节流、被拦、批卡建档(真库,integration)。

抓取和读图用桩(不出网),建档走 K 真的 create_product,建完回读。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.agent_series.suqinghe import cards, dossier as dossier_mod, dossiers, executor
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier
from backend.app.modules.agent_series.suqinghe.sourcing_1688 import parse_capture
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeAIEvent,
    KProductKnowledgeAttribute,
    KProductKnowledgeMediaAsset,
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)
from backend.app.modules.k_series.product_knowledge.scope_shim import KScopeContext
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import OWNER, REGULAR, _login, people  # noqa: F401 —— 复用同一套人和登录
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent / "fixtures" / "sqh1688"
OFFER = "1057528621016"
URL = f"https://detail.1688.com/offer/{OFFER}.html"
T0 = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)


def _capture() -> dict:
    return parse_capture(
        url=URL,
        html=(FIXTURE / f"offer_{OFFER}.html").read_text(encoding="utf-8"),
        text=(FIXTURE / f"offer_{OFFER}.txt").read_text(encoding="utf-8"),
        desc_js=(FIXTURE / f"offer_{OFFER}.desc.txt").read_text(encoding="utf-8"),
    ).to_dict()


def _fetch(url: str) -> dict:
    return _capture()


def _read(db, capture: dict) -> dict:
    return {"facts": [], "segments_seen": 9, "segments_read": 0, "cost_usd": 0.0, "stopped_reason": None}


def _build(db, capture: dict, image_read: dict) -> dict:
    draft = dossier_mod.build_draft(
        db,
        capture,
        image_read,
        writer=lambda payload: {"name_en": "Squishy Dumpling Stress Relief Toy", "variant_names": [], "package_includes": []},
        # 类目判不出 → 不绑类目(测试库里没有谷歌类目树),建档照样成功。
        classifier=lambda db, text: type("V", (), {"status": "none", "chosen": None})(),
    )
    draft["reference_images"] = []  # 不出网下载图片
    return draft


@pytest.fixture
def clean(people, monkeypatch):  # noqa: F811
    def wipe():
        with without_org_data_isolation(), SessionLocal() as db:
            db.execute(delete(SqhDossier))
            ids = select(KProductKnowledgeProduct.id).where(KProductKnowledgeProduct.source_system == "1688")
            # AI 事件是 K 批卖点/生成时记的审计行(10-27 文案测试真调 K 的卖点审批后出现),外键挂在产品上,先删
            for child in (KProductKnowledgeMediaAsset, KProductKnowledgeAttribute, KProductKnowledgeVariant, KProductKnowledgeAIEvent):
                db.execute(delete(child).where(child.product_id.in_(ids)))
            db.execute(delete(KProductKnowledgeProduct).where(KProductKnowledgeProduct.source_system == "1688"))
            db.commit()

    wipe()
    monkeypatch.setattr(
        executor,
        "_scope",
        lambda db: KScopeContext(workspace_key=DEFAULT_TEST_ORG_DB_ID, business_context="independent_store", scope_mode="production"),
    )
    yield people
    wipe()


def _process(now: datetime) -> SqhDossier | None:
    with without_org_data_isolation(), SessionLocal() as db:
        return dossiers.process_next(db, now=now, fetch=_fetch, read=_read, build=_build)


def _build_approved() -> dict | None:
    """worker 那一步:捡一单批了还没建的去建。"""
    with without_org_data_isolation(), SessionLocal() as db:
        waiting = executor.approved_waiting(db)
        return executor.build_approved(db, *waiting[0]) if waiting else None


def test_submit_is_owner_only_and_everyone_can_read(clean, auth_client: TestClient) -> None:
    _login(auth_client, REGULAR)
    assert auth_client.post("/api/app/suqinghe/dossiers", json={"url": URL}).status_code == 403
    _login(auth_client, OWNER)
    bad = auth_client.post("/api/app/suqinghe/dossiers", json={"url": "https://www.amazon.com/dp/B0TESTTEST"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "SQH_DOSSIER_NOT_1688"
    first = auth_client.post("/api/app/suqinghe/dossiers", json={"url": URL + "?spm=x"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True and body["position"] == 1 and body["status"] == "queued" and "排在第 1 个" in body["reply"]
    again = auth_client.post("/api/app/suqinghe/dossiers", json={"url": URL}).json()
    assert again["created"] is False and again["id"] == body["id"]

    _login(auth_client, REGULAR)
    listed = auth_client.get("/api/app/suqinghe/dossiers")
    assert listed.status_code == 200 and listed.json()["items"][0]["offer_id"] == OFFER
    detail = auth_client.get(f"/api/app/suqinghe/dossiers/{body['id']}")
    assert detail.status_code == 200 and detail.json()["capture"]["submitted_url"].endswith("spm=x")
    assert auth_client.get("/api/app/suqinghe/dossiers/999999").status_code == 404


def test_process_throttle_then_approve_creates_k_product_and_dedupes(clean, auth_client: TestClient) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="c19")
        db.commit()
    ready = _process(T0)
    assert ready is not None and ready.status == "ready" and ready.card_ref
    assert ready.flagged_count >= 1  # 售价至少要老板定

    # 节流:同一分钟里再来一单不开页面
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(SqhDossier(source_url="https://detail.1688.com/offer/123456789.html", offer_id="123456789", status="queued", channel="web", capture={}, draft={}))
        db.commit()
    assert _process(T0 + timedelta(seconds=20)) is None

    _login(auth_client, OWNER)
    resp = auth_client.post(f"/api/app/suqinghe/cards/{ready.card_ref}/decide", json={"decision": "approve"})
    assert resp.status_code == 200, resp.text
    # 点「批」只落「已批」就回;真的建交给 worker(10-26:原来同步建、下参考图,点一下等 3–9 秒)
    assert resp.json()["execution"] == {"ok": True, "queued": True, "note": cards.BUILD_QUEUED_NOTE}
    listed = {item["id"]: item for item in auth_client.get("/api/app/suqinghe/dossiers").json()["items"]}
    assert listed[ready.id]["status"] == "ready" and listed[ready.id]["building"] is True
    execution = _build_approved()
    assert execution["ok"] is True and execution["created"] is True, execution
    detail = auth_client.get(f"/api/app/suqinghe/dossiers/{ready.id}").json()
    assert detail["status"] == "created" and detail["building"] is False

    with without_org_data_isolation(), SessionLocal() as db:
        saved = db.get(SqhDossier, ready.id)
        assert saved.status == "created" and saved.k_product_id == execution["k_product_id"]
        product = db.scalar(select(KProductKnowledgeProduct).where(KProductKnowledgeProduct.source_record_id == OFFER))
        assert product is not None
        assert product.source_system == "1688" and product.product_type == "simple_product"
        assert product.product_name_en == "Squishy Dumpling Stress Relief Toy"
        assert product.sku and product.workspace_key == DEFAULT_TEST_ORG_DB_ID
        assert "SKU" in product.raw_input_text

    # 同一个 offer 再整理一次、再批:认领已有产品,不重复建
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhDossier).where(SqhDossier.offer_id == "123456789"))
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    second = _process(T0 + timedelta(minutes=5))
    assert second is not None and second.status == "ready"
    assert auth_client.post(f"/api/app/suqinghe/cards/{second.card_ref}/decide", json={"decision": "approve"}).json()["execution"]["queued"] is True
    again = _build_approved()
    assert again["ok"] is True and again["created"] is False and again["k_product_id"] == execution["k_product_id"]
    with without_org_data_isolation(), SessionLocal() as db:
        count = db.scalars(select(KProductKnowledgeProduct).where(KProductKnowledgeProduct.source_record_id == OFFER)).all()
        assert len(count) == 1


def test_reject_marks_dossier_rejected_and_nothing_is_built(clean) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)
    with without_org_data_isolation(), SessionLocal() as db:
        owner = db.get(User, clean["owner"])
        out = cards.decide_card(db, card_id=ready.card_ref, decision="reject", actor=owner, channel="web", reason="这个品不做")
        db.commit()
        assert out.execution == {"ok": True, "note": "档案已驳回,不建。"}
        assert db.get(SqhDossier, ready.id).status == "rejected"
        assert db.scalar(select(KProductKnowledgeProduct).where(KProductKnowledgeProduct.source_record_id == OFFER)) is None


def test_executor_failure_is_recorded_not_swallowed(clean, monkeypatch) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)

    def boom(*args, **kwargs):
        raise RuntimeError("K 建档挂了")

    monkeypatch.setattr("backend.app.modules.k_series.product_knowledge.service.create_product", boom)
    with without_org_data_isolation(), SessionLocal() as db:
        owner = db.get(User, clean["owner"])
        out = cards.decide_card(db, card_id=ready.card_ref, decision="approve", actor=owner, channel="web")
        db.commit()
        assert out.execution["queued"] is True
    outcome = _build_approved()
    assert outcome["ok"] is False and "K 建档挂了" in outcome["note"] and outcome["card_ref"] == ready.card_ref
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.get(SqhDossier, ready.id).status == "failed"
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ready.card_ref))
        assert card.status == "approved" and "执行失败" in (card.decision_reason or "")
    assert _build_approved() is None  # 记过账的不会再被捡起来反复建


def test_approve_returns_at_once_and_redo_waits_for_the_build(clean, monkeypatch) -> None:
    # 10-26:老板点「批」要等 3–9 秒 —— 请求里同步建档、从 1688 CDN 一张张下参考图。现在请求里一步都不建。
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)

    def must_not_build(*args, **kwargs):
        raise AssertionError("点「批」的请求里不该建档")

    real_build = executor.create_k_from_dossier
    monkeypatch.setattr(executor, "create_k_from_dossier", must_not_build)
    with without_org_data_isolation(), SessionLocal() as db:
        owner = db.get(User, clean["owner"])
        out = cards.decide_card(db, card_id=ready.card_ref, decision="approve", actor=owner, channel="web")
        db.commit()
        assert out.execution["queued"] is True and db.get(SqhDossier, ready.id).status == "ready"
        # 批了、还没建完:不许重新整理 —— 驳卡驳不动,档案却会被标驳回,就没人去建了
        with pytest.raises(dossiers.DossierError, match="正在建进 K"):
            dossiers.redo(db, dossier_id=ready.id, actor=owner)
        db.rollback()
        assert [d.id for d, _ in executor.approved_waiting(db)] == [ready.id]
    monkeypatch.setattr(executor, "create_k_from_dossier", real_build)
    assert _build_approved()["ok"] is True
    with without_org_data_isolation(), SessionLocal() as db:
        assert db.get(SqhDossier, ready.id).status == "created" and executor.approved_waiting(db) == []


def test_approving_a_card_whose_dossier_is_not_ready_is_recorded(clean) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)
    with without_org_data_isolation(), SessionLocal() as db:
        db.get(SqhDossier, ready.id).status = "failed"
        db.commit()
        owner = db.get(User, clean["owner"])
        out = cards.decide_card(db, card_id=ready.card_ref, decision="approve", actor=owner, channel="web")
        db.commit()
        assert out.execution["ok"] is False and "不是「待批」" in out.execution["note"]
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ready.card_ref))
        assert card.status == "approved" and "执行失败" in (card.decision_reason or "")
    assert _build_approved() is None


def test_blocked_page_marks_blocked_and_raises_one_alert(clean) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        result = dossiers.process_next(
            db, now=T0, fetch=lambda url: {"offer_id": OFFER, "blocked": True, "block_reason": "跳到登录页"}, read=_read, build=_build
        )
        assert result.status == "blocked" and "登录" in (result.error or "")
        alerts = db.scalars(select(SqhCard).where(SqhCard.kind == "ops_alert")).all()
        assert len(alerts) == 1 and alerts[0].title == "1688 把我拦住了"


def test_redo_rejects_old_card_and_requeues_same_link(clean, auth_client: TestClient) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)
    assert ready is not None and ready.status == "ready" and ready.card_ref

    _login(auth_client, REGULAR)
    assert auth_client.post(f"/api/app/suqinghe/dossiers/{ready.id}/redo").status_code == 403

    _login(auth_client, OWNER)
    resp = auth_client.post(f"/api/app/suqinghe/dossiers/{ready.id}/redo")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] is True and body["status"] == "queued" and body["id"] != ready.id and body["offer_id"] == OFFER

    with without_org_data_isolation(), SessionLocal() as db:
        assert db.get(SqhDossier, ready.id).status == "rejected"
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ready.card_ref))
        assert card.status == "rejected" and card.decision_reason == dossiers.REDO_REASON

    # 还在排队的不能再重做;不存在的 404 也不给,统一 422 说清楚
    again = auth_client.post(f"/api/app/suqinghe/dossiers/{body['id']}/redo")
    assert again.status_code == 422 and "整理中" in again.json()["detail"]["message"]
    missing = auth_client.post("/api/app/suqinghe/dossiers/999999/redo")
    assert missing.status_code == 422 and "没有这份档案" in missing.json()["detail"]["message"]


# ---------------------------------------------------------------- 10-28:登录浏览器——被拦留页等老板、过了接着做;「今天先不碰」真的不碰;浏览器接口


class _FakeBrowser:
    def __init__(self) -> None:
        self.noted: list[int] = []

    def note_dossier(self, dossier_id: int) -> None:
        self.noted.append(dossier_id)

    def take_recovered(self):
        return None


def _fetch_needs_human(url: str) -> dict:
    return {"blocked": True, "block_reason": "needs_human:captcha_page", "offer_id": OFFER, "url": url}


def _fetch_blocked(url: str) -> dict:
    return {"blocked": True, "block_reason": "captcha_page", "offer_id": OFFER, "url": url}


def _recovered_event(dossier_id: int) -> dict:
    return {
        "outcome": "recovered",
        "dossier_id": dossier_id,
        "final_url": URL,
        "title": "捏捏乐 - 阿里巴巴",
        "html": (FIXTURE / f"offer_{OFFER}.html").read_text(encoding="utf-8"),
        "text": (FIXTURE / f"offer_{OFFER}.txt").read_text(encoding="utf-8"),
    }


def test_blocked_page_waits_for_the_boss_then_resumes_into_a_ready_dossier(clean, monkeypatch) -> None:
    from backend.app.modules.agent_series.suqinghe import browser, sourcing_1688

    fake = _FakeBrowser()
    monkeypatch.setenv("SQH_BROWSER", "1")
    monkeypatch.setattr(browser, "get", lambda: fake)
    monkeypatch.setattr(sourcing_1688, "fetch_detail_description", lambda url, **kw: ((FIXTURE / f"offer_{OFFER}.desc.txt").read_text(encoding="utf-8"), None))
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        held = dossiers.process_next(db, now=T0, fetch=_fetch_needs_human, read=_read, build=_build)
        assert held is not None and held.status == "needs_human" and held.error == "captcha_page" and fake.noted == [held.id]
        alert = db.scalar(select(SqhCard).where(SqhCard.kind == "ops_alert"))
        assert alert is not None and alert.evidence["browser"] is True and alert.evidence["dossier_id"] == held.id and "打开浏览器" in alert.conclusion
        # 等人期间别的链接不抓(浏览器 holding);这里用假的 status 模拟
        monkeypatch.setattr(browser, "status", lambda: {"status": "needs_human", "reason": "captcha_page", "dossier_id": held.id, "logged_in_at": None, "alive": True})
        dossiers.enqueue(db, url="https://detail.1688.com/offer/777000333.html", actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        calls: list[str] = []
        assert dossiers.process_next(db, now=T0 + timedelta(minutes=5), fetch=lambda url: calls.append(url) or _capture(), read=_read, build=_build) is None
        assert calls == []
        monkeypatch.setattr(browser, "status", lambda: {"status": "idle", "reason": None, "dossier_id": None, "logged_in_at": None, "alive": True})
        # 「重新整理」对等验证的档案说不
        with pytest.raises(dossiers.DossierError):
            dossiers.redo(db, dossier_id=held.id, actor=db.get(User, clean["owner"]))
        # 老板过了验证:浏览器线程交出恢复后的页面,她接着读图、建草稿、发建档卡
        done = dossiers.resume_human(db, now=T0 + timedelta(minutes=6), event=_recovered_event(held.id), read=_read, build=_build)
        assert done is not None and done.id == held.id and done.status == "ready" and done.card_ref
        card = cards.find_card(db, done.card_ref)
        assert card is not None and card.kind == "create_k_dossier"
        # 没有事件 / 事件对不上档案:什么都不做
        assert dossiers.resume_human(db, event=None) is None
        assert dossiers.resume_human(db, event={"outcome": "recovered", "dossier_id": done.id}) is None  # 已经不是 needs_human


def test_giving_up_marks_blocked_and_restart_requeues(clean, monkeypatch) -> None:
    from backend.app.modules.agent_series.suqinghe import browser

    monkeypatch.setenv("SQH_BROWSER", "1")
    monkeypatch.setattr(browser, "get", lambda: _FakeBrowser())
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        held = dossiers.process_next(db, now=T0, fetch=_fetch_needs_human, read=_read, build=_build)
        gave_up = dossiers.resume_human(db, event={"outcome": "gave_up", "dossier_id": held.id, "reason": "等了 120 分钟没人来过验证"})
        assert gave_up is not None and gave_up.status == "blocked" and "120 分钟" in gave_up.error
        # 再排一份进 needs_human,模拟 worker 重启:回队列
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        monkeypatch.setenv("SQH_1688_RETRY_AFTER_BLOCK", "1")  # 上面那份今天已经 blocked,先放开闸
        held2 = dossiers.process_next(db, now=T0 + timedelta(minutes=2), fetch=_fetch_needs_human, read=_read, build=_build)
        assert held2 is not None and held2.status == "needs_human"
        assert dossiers.requeue_needs_human(db) == 1
        db.refresh(held2)
        assert held2.status == "queued" and held2.error is None


def test_blocked_today_really_means_no_more_1688_today(clean, monkeypatch) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        blocked = dossiers.process_next(db, now=T0, fetch=_fetch_blocked, read=_read, build=_build)
        assert blocked is not None and blocked.status == "blocked"
        dossiers.enqueue(db, url="https://detail.1688.com/offer/777000333.html", actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        calls: list[str] = []
        fetch = lambda url: calls.append(url) or _capture()  # noqa: E731
        assert dossiers.process_next(db, now=T0 + timedelta(minutes=5), fetch=fetch, read=_read, build=_build) is None and calls == []
        monkeypatch.setenv("SQH_1688_RETRY_AFTER_BLOCK", "1")
        assert dossiers.process_next(db, now=T0 + timedelta(minutes=5), fetch=fetch, read=_read, build=_build) is not None and calls
        monkeypatch.delenv("SQH_1688_RETRY_AFTER_BLOCK")
        # 第二天照常
        dossiers.enqueue(db, url="https://detail.1688.com/offer/777000444.html", actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
        assert dossiers.process_next(db, now=T0 + timedelta(days=1), fetch=fetch, read=_read, build=_build) is not None


def test_browser_endpoints_everyone_reads_only_owner_acts(clean, auth_client: TestClient) -> None:
    from backend.app.modules.agent_series.suqinghe.models import SqhBrowser, SqhBrowserInput

    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhBrowserInput))
        row = db.get(SqhBrowser, 1) or SqhBrowser(id=1)
        row.status, row.frame, row.frame_at, row.viewer_seen_at = "idle", None, None, None
        db.add(row)
        db.commit()
    assert auth_client.get("/api/app/suqinghe/browser").status_code == 401
    _login(auth_client, REGULAR)
    res = auth_client.get("/api/app/suqinghe/browser?viewer=1")
    assert res.status_code == 200 and res.json()["status"] == "idle"
    assert auth_client.get("/api/app/suqinghe/browser/frame").status_code == 404
    assert auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "click", "payload": {"x": 1, "y": 2}}).status_code == 403
    assert auth_client.post("/api/app/suqinghe/browser/login").status_code == 403
    with without_org_data_isolation(), SessionLocal() as db:
        seen = db.get(SqhBrowser, 1).viewer_seen_at
        assert seen is not None  # 看一眼就记下「有人在看」,worker 据此才截图
        db.get(SqhBrowser, 1).frame = b"\xff\xd8\xff\xe0fakejpeg"
        db.commit()
    frame = auth_client.get("/api/app/suqinghe/browser/frame")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg" and frame.headers["cache-control"] == "no-store" and frame.content.startswith(b"\xff\xd8")
    _login(auth_client, OWNER)
    ok = auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "down", "payload": {"x": 100.26, "y": 500}})
    assert ok.status_code == 200 and ok.json()["queued"] is True
    assert auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "click", "payload": {"x": 5000, "y": 1}}).status_code == 422
    assert auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "key", "payload": {"key": "F12"}}).status_code == 422
    assert auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "navigate", "payload": {"url": "https://evil.example/"}}).status_code == 422
    assert auth_client.post("/api/app/suqinghe/browser/input", json={"kind": "type", "payload": {"text": "abc"}}).status_code == 200
    assert auth_client.post("/api/app/suqinghe/browser/login").status_code == 200
    assert auth_client.post("/api/app/suqinghe/browser/close").status_code == 200
    with without_org_data_isolation(), SessionLocal() as db:
        rows = db.scalars(select(SqhBrowserInput).order_by(SqhBrowserInput.id)).all()
        assert [(r.kind, r.payload) for r in rows] == [("down", {"x": 100.3, "y": 500.0}), ("type", {"text": "abc"}), ("login", {}), ("close", {})]
        assert all(r.applied_at is None for r in rows)
    # 办公室全景里也带浏览器状态
    office = auth_client.get("/api/app/suqinghe/office").json()
    assert office["browser"]["status"] == "idle" and "logged_in_at" in office["browser"]
