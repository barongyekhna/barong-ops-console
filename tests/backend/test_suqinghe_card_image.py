"""卡片缩略图(10-27 卡片重做):每种卡都从同一个口子拿图——选品卡走 F 缓存、带 K 产品的卡走 K 媒资缩略图、带档案的卡走档案参考图;
都没有就 404。真库 integration(建卡、建媒资行),出网和派生图打桩。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.db.session import SessionLocal
from backend.app.modules.agent_series.suqinghe import cards
from backend.app.modules.agent_series.suqinghe.constants import CANDIDATE_CARD_KIND, DOSSIER_CARD_KIND
from backend.app.modules.agent_series.suqinghe.models import SqhCard, SqhDossier
from backend.app.modules.agent_series.suqinghe.pipeline import PRICE_CARD_KIND
from backend.app.modules.k_series.product_knowledge.models import KProductKnowledgeMediaAsset
from backend.app.services.data_isolation import without_org_data_isolation
from tests.backend.test_suqinghe_cards_api import OWNER, _login, people  # noqa: F401
from tests.backend.test_suqinghe_dossiers_api import T0, URL, _build_approved, _process, clean  # noqa: F401

pytestmark = pytest.mark.integration
PREFIX = "sqh-img-test"


@pytest.fixture
def built(clean):  # noqa: F811
    """一个批过、建进 K 的产品(照流水线测试的做法)。"""
    from backend.app.modules.agent_series.suqinghe import dossiers

    with without_org_data_isolation(), SessionLocal() as db:
        dossiers.enqueue(db, url=URL, actor_user_id=str(clean["owner"]), channel="web")
        db.commit()
    ready = _process(T0)
    with without_org_data_isolation(), SessionLocal() as db:
        from backend.app.models.user import User

        cards.decide_card(db, card_id=ready.card_ref, decision="approve", actor=db.get(User, clean["owner"]), channel="web")
        db.commit()
    outcome = _build_approved()
    assert outcome and outcome["ok"], outcome
    yield ready.id, outcome["k_product_id"], clean["owner"]
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(SqhCard).where(SqhCard.title.like(f"{PREFIX}%")))
        db.commit()


def _card(kind: str, evidence: dict[str, Any], *, title: str = f"{PREFIX} 卡") -> str:
    with without_org_data_isolation(), SessionLocal() as db:
        card, _ = cards.create_card(db, dedupe_key=f"{PREFIX}:{uuid4()}", kind=kind, title=title, conclusion="c", evidence=evidence)
        db.commit()
        return card.ref


def _asset(product_id: str, *, role: str, status: str, position: int | None = None, object_key: str | None = "k/test.webp") -> str:
    with without_org_data_isolation(), SessionLocal() as db:
        row = KProductKnowledgeMediaAsset(
            product_id=product_id,
            asset_type="image",
            asset_role=role,
            status=status,
            review_status="pending",
            mime_type="image/webp",
            object_key=object_key,
            metadata_json={"position": position} if position is not None else {},
        )
        db.add(row)
        db.commit()
        return str(row.id)


def test_image_source_picks_the_best_product_image_then_dossier_reference(built) -> None:
    dossier_id, product_id, _ = built
    staged2 = _asset(product_id, role="gallery", status="staged", position=2)
    staged1 = _asset(product_id, role="main", status="staged", position=1)
    reference = _asset(product_id, role="reference", status="available")
    no_file = _asset(product_id, role="main", status="available", object_key=None)
    price_ref = _card(PRICE_CARD_KIND, {"dossier_id": dossier_id, "k_product_id": product_id, "sku": "X"})
    dossier_ref = _card(DOSSIER_CARD_KIND, {"dossier_id": dossier_id, "offer_id": "1"})
    plain_ref = _card("ops_alert", {"issue": "worker:x"})
    with without_org_data_isolation(), SessionLocal() as db:
        kind, row = cards.image_source(db, cards.find_card(db, price_ref))
        assert kind == "k_asset" and str(row.id) == staged1  # 没有可用主图(那条没文件) → 暂存出图第 1 张
        main = _asset(product_id, role="main", status="available")
        kind, row = cards.image_source(db, cards.find_card(db, price_ref))
        assert kind == "k_asset" and str(row.id) == main  # 可用的主图最优先
        # 建档卡:档案里的参考图(1688 CDN)
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**(dossier.draft or {}), "reference_images": ["https://cbu01.alicdn.com/img/ibank/ref.jpg"]}
        db.commit()
        assert cards.image_source(db, cards.find_card(db, dossier_ref)) == ("f", (f"dossier-{dossier_id}", "https://cbu01.alicdn.com/img/ibank/ref.jpg"))
        assert cards.image_source(db, cards.find_card(db, plain_ref)) is None
        del staged2, reference, no_file
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(KProductKnowledgeMediaAsset).where(KProductKnowledgeMediaAsset.product_id == product_id, KProductKnowledgeMediaAsset.object_key.is_(None)))
        db.commit()


def test_card_image_endpoint_serves_k_thumbnail_dossier_reference_and_404s(built, auth_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend.app.modules.f_series.enrichment import images as f_images
    from backend.app.modules.k_series.product_knowledge import router as k_router

    dossier_id, product_id, _ = built
    _asset(product_id, role="main", status="available")
    price_ref = _card(PRICE_CARD_KIND, {"dossier_id": dossier_id, "k_product_id": product_id, "sku": "X"})
    dossier_ref = _card(DOSSIER_CARD_KIND, {"dossier_id": dossier_id, "offer_id": "1"})
    pick_ref = _card(CANDIDATE_CARD_KIND, {"f_candidate_id": str(uuid4()), "image_url": "https://cbu01.alicdn.com/img/ibank/pick.jpg"})
    plain_ref = _card("ops_alert", {"issue": "worker:x"})
    with without_org_data_isolation(), SessionLocal() as db:
        dossier = db.get(SqhDossier, dossier_id)
        dossier.draft = {**(dossier.draft or {}), "reference_images": [{"url": "https://cbu01.alicdn.com/img/ibank/ref.jpg"}]}
        db.commit()
    thumb = tmp_path / "thumb.webp"
    thumb.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    monkeypatch.setattr(k_router, "_ensure_media_asset_derivative", lambda row, *, kind, max_side: thumb)
    fetched: list[tuple[str, str]] = []
    monkeypatch.setattr(f_images, "get_candidate_image", lambda cid, url, variant: fetched.append((cid, url)) or (b"\x89PNG", "image/png"))
    _login(auth_client, OWNER)

    res = auth_client.get(f"/api/app/suqinghe/cards/{price_ref}/image")
    assert res.status_code == 200 and res.headers["content-type"].startswith("image/webp") and res.content.startswith(b"RIFF")
    res = auth_client.get(f"/api/app/suqinghe/cards/{dossier_ref}/image")
    assert res.status_code == 200 and fetched[-1] == (f"dossier-{dossier_id}", "https://cbu01.alicdn.com/img/ibank/ref.jpg")
    res = auth_client.get(f"/api/app/suqinghe/cards/{pick_ref}/image")
    assert res.status_code == 200 and fetched[-1][1].endswith("pick.jpg")
    res = auth_client.get(f"/api/app/suqinghe/cards/{plain_ref}/image")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "SQH_CARD_IMAGE_NOT_FOUND"
    assert auth_client.get("/api/app/suqinghe/cards/zzzz/image").status_code == 404
