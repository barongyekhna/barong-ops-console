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
            for child in (KProductKnowledgeMediaAsset, KProductKnowledgeAttribute, KProductKnowledgeVariant):
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
    execution = resp.json()["execution"]
    assert execution["ok"] is True and execution["created"] is True, execution

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
    again = auth_client.post(f"/api/app/suqinghe/cards/{second.card_ref}/decide", json={"decision": "approve"}).json()["execution"]
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
        assert out.execution["ok"] is False and "K 建档挂了" in out.execution["note"]
        assert db.get(SqhDossier, ready.id).status == "failed"
        card = db.scalar(select(SqhCard).where(SqhCard.ref == ready.card_ref))
        assert card.status == "approved" and "执行失败" in (card.decision_reason or "")


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
