"""苏青禾 1688 → K 档案草稿:合并、标红、建档参数、节流、链接收件(unit,不连库、不出网)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.modules.agent_series.suqinghe import dossier, dossiers, executor, worker_main
from backend.app.modules.agent_series.suqinghe.sourcing_1688 import parse_capture
from backend.app.modules.k_series.product_knowledge.schemas import ProductKnowledgeCreate

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "sqh1688"
OFFER = "1057528621016"


@pytest.fixture(scope="module")
def capture() -> dict:
    html = (FIXTURE / f"offer_{OFFER}.html").read_text(encoding="utf-8")
    text = (FIXTURE / f"offer_{OFFER}.txt").read_text(encoding="utf-8")
    desc = (FIXTURE / f"offer_{OFFER}.desc.txt").read_text(encoding="utf-8")
    return parse_capture(url=f"https://detail.1688.com/offer/{OFFER}.html", html=html, text=text, desc_js=desc).to_dict()


IMAGE_READ = {
    "facts": [
        # 包装盒上印的是 AGES 3+,页面属性写的是 青年(15-35岁)—— 必须标 conflict,不替老板选。
        {"field": "age_range", "value": "3+", "unit": None, "raw_text": "AGES 3+", "image_index": 2, "segment_index": 0, "confidence": "high"},
        {"field": "package_includes", "value": "12 个/盒", "unit": None, "raw_text": "拍12个为一大盒", "image_index": 2, "segment_index": 0, "confidence": "medium"},
    ],
    "segments_seen": 9,
    "segments_read": 3,
    "cost_usd": 0.12,
    "stopped_reason": None,
}


def _writer(payload: dict) -> dict:
    return {
        "name_en": "Squishy Dumpling Stress Relief Toy, Glitter Bead Squeeze Ball",
        "variant_names": [f"Style {i + 1}" for i in range(len(payload["variant_names"]))],
        "package_includes": ["12 squishy toys per box"],
    }


@dataclass
class _Cand:
    id: str = "3166"
    name: str = "Toys"
    full_path: str = "Toys & Games > Toys"
    name_zh: str = "玩具"


def _classifier(confidence: str):
    return lambda db, text: SimpleNamespace(status="ok", chosen=_Cand(), path=["Toys & Games", "Toys"], confidence=confidence, reason_zh="捏捏乐属于玩具")


def _draft(capture, **kw):
    return dossier.build_draft(None, capture, IMAGE_READ, writer=kw.get("writer", _writer), classifier=kw.get("classifier", _classifier("high")))


def test_age_conflict_is_flagged_not_resolved(capture) -> None:
    draft = _draft(capture)
    age = draft["specs"]["age_range"]
    assert age["status"] == "conflict"
    assert age["value"] is None
    kinds = {s["kind"] for s in age["sources"]}
    assert {"image"} <= kinds and ({"page_text"} & kinds or {"page_json"} & kinds)
    assert "3+" in age["note"]


def test_placeholders_count_as_missing_and_brand_is_dropped(capture) -> None:
    draft = _draft(capture)
    material = draft["specs"].get("material")
    assert material is not None and material["status"] == "missing"  # 玩具材质:其它
    assert all("品牌" not in a["name"] for a in draft["other_attributes"])
    assert "brand" not in draft["specs"]


def test_retail_price_always_needs_owner_and_variable_detected(capture) -> None:
    draft = _draft(capture)
    assert draft["fields"]["retail_price"]["status"] == "needs_owner"
    assert "进价" in draft["fields"]["retail_price"]["note"]
    assert draft["fields"]["product_type"]["value"] == "variable_product"
    assert len(draft["variants"]) == len(capture["skus"]) > 1
    assert all(v["name_en"] for v in draft["variants"])
    assert draft["flagged_count"] == len(draft["flagged"]) >= 2


def test_non_english_name_is_missing_and_low_confidence_category_needs_owner(capture) -> None:
    draft = _draft(capture, writer=lambda payload: {"name_en": "仿真包子捏捏乐", "variant_names": []}, classifier=_classifier("low"))
    assert draft["fields"]["name_en"]["status"] == "missing"
    assert draft["fields"]["category"]["status"] == "needs_owner"
    assert draft["fields"]["category"]["value"]["google_category_id"] == "3166"


def test_writer_failure_never_invents(capture) -> None:
    def boom(payload):
        raise RuntimeError("offline")

    draft = _draft(capture, writer=boom)
    assert draft["fields"]["name_en"]["status"] == "missing"
    assert draft["fields"]["package_includes"]["status"] == "missing"


def test_reference_images_only_alicdn(capture) -> None:
    draft = _draft(capture)
    assert draft["reference_images"]
    assert all("alicdn.com" in url for url in draft["reference_images"])
    assert len(draft["reference_images"]) <= 8


def test_create_payload_passes_k_validation(capture) -> None:
    draft = _draft(capture)
    fake = SimpleNamespace(id=7, offer_id=OFFER, source_url=f"https://detail.1688.com/offer/{OFFER}.html", draft=draft)
    payload = executor.build_create_payload(fake)
    assert payload["product_type"] == "simple_product"  # 售价没定,先建单品草稿(见 executor 文档)
    assert payload["source_system"] == "1688" and payload["source_record_id"] == OFFER
    assert payload["product_name_en"].startswith("Squishy")
    assert "SKU" in payload["raw_input_text"] and "售价未定" in payload["manual_notes"]
    request = ProductKnowledgeCreate(**payload)  # 规格是 operator 形状、没品牌,K 的校验要能过
    assert request.structured_specs_json is None or request.structured_specs_json["source"]["platform"] == "operator"
    assert request.package_includes_json == ["12 squishy toys per box"]


def test_throttle_rules() -> None:
    now = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)
    assert dossiers.throttle_ok(now=now, last_fetch=None, fetched_today=0, limit=30)[0] is True
    assert dossiers.throttle_ok(now=now, last_fetch=now - timedelta(seconds=30), fetched_today=1, limit=30)[0] is False
    assert dossiers.throttle_ok(now=now, last_fetch=now - timedelta(seconds=61), fetched_today=1, limit=30)[0] is True
    ok, why = dossiers.throttle_ok(now=now, last_fetch=None, fetched_today=30, limit=30)
    assert ok is False and "上限" in why


def test_find_1688_links_in_chat_text() -> None:
    text = (
        "老板:这个帮我整理 https://detail.1688.com/offer/1057528621016.html?spm=a26352 "
        "还有这个 https://detail.1688.com/offer/1057528621016.html 重复的,"
        "以及 https://www.amazon.com/dp/B0TEST 不是 1688"
    )
    links = dossiers.find_1688_links(text)
    assert [offer for _, offer in links] == ["1057528621016"]
    assert dossiers.find_1688_links("批 #a3f9") == []


def test_queue_reply_wording() -> None:
    assert "排在第 2 个" in dossiers.queue_reply(2, created=True, status="queued")
    assert "已经整理好了" in dossiers.queue_reply(0, created=False, status="ready")


def test_decided_text_reports_execution() -> None:
    card = SimpleNamespace(ref="a3f9", title="建 K 档案:包子", status="approved", decided_via="web")
    ok = worker_main.decided_text(card, changed=True, decision="approve", execution={"ok": True, "note": "建好了:K 产品 TOY-001"})
    assert "TOY-001" in ok
    bad = worker_main.decided_text(card, changed=True, decision="approve", execution={"ok": False, "note": "回读不一致"})
    assert "没做成" in bad


def test_package_fact_never_leaks_into_age_and_origin_levels_do_not_conflict(capture) -> None:
    draft = _draft(capture)
    age = draft["specs"]["age_range"]
    assert "12" not in age["note"]  # 「12 个/盒」是包装内容,不是年龄
    assert draft["specs"]["origin_region"]["status"] == "ok"
    assert draft["specs"]["origin_country"]["status"] == "ok"
    assert dossier._spec_key("package_includes") is None
    assert dossier._spec_key("Age range") == "age_range"
    assert dossier._spec_key("Package type") == "packaging"


def test_scoped_weight_does_not_conflict_and_carton_stays_out_of_package() -> None:
    from backend.app.modules.agent_series.suqinghe import dossier as d

    capture = {"attributes": [], "title_zh": "捏捏乐"}
    facts = [
        {"field": "weight", "value": "约200", "unit": "克", "scope": "item", "raw_text": "一个约200克", "image_index": 0, "segment_index": 0},
        {"field": "weight", "value": "约2500", "unit": "克", "scope": "inner_pack", "raw_text": "一大盒约2500克", "image_index": 1, "segment_index": 0},
        {"field": "dimensions", "value": "33×21×12", "unit": "cm", "scope": "carton", "raw_text": "外箱33×21×12cm", "image_index": 2, "segment_index": 0},
    ]
    specs, _ = d.merge_specs(capture, facts)
    assert specs["weight"]["status"] == "ok"
    assert specs["weight_pack"]["status"] == "ok"
    assert specs["dimensions_carton"]["status"] == "ok"
    assert "dimensions" not in specs


def test_category_note_distinguishes_offline_from_no_match() -> None:
    from types import SimpleNamespace

    from backend.app.modules.agent_series.suqinghe import dossier as d

    offline = d._category_field(None, "x", lambda db, t: SimpleNamespace(status="offline", chosen=None))
    assert "没接通" in offline["note"]
    none = d._category_field(
        None, "x", lambda db, t: SimpleNamespace(status="none", chosen=None, shortlist_size=0, hint=SimpleNamespace(keywords_en=["squishy toy"]))
    )
    assert "squishy toy" in none["note"] and "候选 0 个" in none["note"]
