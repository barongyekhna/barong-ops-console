"""苏青禾 1688 → K 档案草稿:合并、标红、建档参数、节流、链接收件(unit,不连库、不出网)。"""

from __future__ import annotations

import json
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


LIVE_DRAFTS = FIXTURE / "live_drafts_20261026.json"  # 10-26 线上三份档案的草稿原样:#7 电池、#8 灭蚊灯、#9 电钻


def _k_spec_rows(offer_id: str) -> tuple[list[dict], dict]:
    live = json.loads(LIVE_DRAFTS.read_text(encoding="utf-8"))[offer_id]
    fake = SimpleNamespace(
        id=live["dossier_id"], offer_id=offer_id, source_url=f"https://detail.1688.com/offer/{offer_id}.html", draft=live["draft"]
    )
    request = ProductKnowledgeCreate(**executor.build_create_payload(fake))  # 先过 K 的建档校验
    return request.structured_specs_json["additional_specs"], live["draft"]


@pytest.mark.parametrize("offer_id", ["643348607768", "773137484620", "888786557113"])
def test_specs_reach_k_named_by_what_they_are(offer_id: str) -> None:
    """进 K 的规格行:名字是「重量、电压…」,出处进出处栏。

    10-26:名字写成了出处(「详情图 12 · 第 1 段」「商品标题」),同一段图读出两条就重名,K 的规格面板里认不出哪行是什么。
    上面那条只验了 K 收不收,没验写进去的对不对。
    """
    rows, draft = _k_spec_rows(offer_id)
    ok = {key: item for key, item in draft["specs"].items() if item["status"] == "ok"}
    assert [row["key"] for row in rows] == [f"sqh_{key}" for key in ok]
    for row, (key, item) in zip(rows, ok.items()):
        assert row["label"] == dossier.SPEC_LABELS_ZH[key]
        assert row["source_label"] == item["sources"][0]["ref"]
    assert len({row["label"] for row in rows}) == len(rows)


def test_battery_spec_panel_in_k() -> None:
    """电池那单进 K 后,规格面板逐行是这样(老板要一眼看懂)。"""
    rows, _ = _k_spec_rows("643348607768")
    assert [(row["label"], row["value"], row["source_label"]) for row in rows] == [
        ("重量(单品)", "166 g", "详情图 12 · 第 1 段"),
        ("电压", "12 V", "商品标题"),
        ("容量", "1300mAh / 1500mAh / 2000mAh / 2500mAh", "规格(SKU)名称"),
        ("材质", "阻燃ABS", "详情图 10 · 第 1 段"),
        ("循环次数", "500 次", "详情图 7 · 第 1 段"),
        ("尺寸(单品)", "84×48×40 mm", "详情图 11 · 第 1 段"),
        ("电池/电芯", "18650、Li-ion、全新A品电芯、锂电工具电池", "详情图 7 · 第 1 段"),
        ("认证", "MSDS、ce、UN38.3、UL 1642 Lithium Batteries、FCC Part 15 Subpart B (Class B)", "属性「产品认证」"),
    ]


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


# ---------------------------------------------------------------- 10-26 第二版:只抄本品、按规格、真矛盾才标红

BATTERY = FIXTURE / "offer_643348607768"
DRILL = FIXTURE / "offer_888786557113"


def _real_capture(base: Path) -> dict:
    offer = base.name.split("_")[1]
    text = base.with_suffix(".txt")
    return parse_capture(
        url=f"https://detail.1688.com/offer/{offer}.html",
        html=base.with_suffix(".html").read_text(encoding="utf-8"),
        text=text.read_text(encoding="utf-8") if text.exists() else "",
        desc_js=base.with_suffix(".desc.txt").read_text(encoding="utf-8"),
    ).to_dict()


def _fact(field: str, value: str, unit: str = "", *, subject: str = "this", confidence: str = "high",
          image: int = 0, segment: int = 0, scope: str = "unknown", raw: str | None = None) -> dict:
    return {"field": field, "value": value, "unit": unit, "raw_text": raw or value, "subject": subject, "variant": "",
            "scope": scope, "confidence": confidence, "image_index": image, "segment_index": segment}


def _draft_with(capture: dict, facts: list[dict], **read) -> dict:
    image_read = {"facts": facts, "segments_seen": 5, "segments_read": 5, "cost_usd": 0.01, "stopped_reason": None, **read}
    return dossier.build_draft(None, capture, image_read, writer=_writer, classifier=_classifier("high"))


def test_other_products_and_slogans_never_become_specs() -> None:
    # 电池那单:一张别款电池图(18V/21V/24V、6.0Ah)+ 一句广告语,第一版全进了「说法不一」。
    facts = [
        _fact("voltage", "12V", "V", image=3),
        _fact("voltage", "21V", "V", subject="other", image=13),
        _fact("voltage", "18V", "V", subject="other", image=13),
        _fact("capacity", "6.0Ah", "Ah", subject="other", image=13),
        _fact("battery_type", "全新A品电芯,足容不虚标,400-500次循环,稳定性高,品质保证", image=7),
    ]
    draft = _draft_with(_real_capture(BATTERY), facts)
    voltage = draft["specs"]["voltage"]
    assert voltage["status"] == "ok" and voltage["value"] == "12" and voltage["unit"] == "V"
    assert not voltage.get("alternatives")
    assert draft["image_read"]["ignored_other"] == 3 and draft["image_read"]["ignored_narrative"] == 1
    assert not any(f["status"] == "conflict" for f in draft["flagged"])


def test_capacity_comes_per_variant_from_sku_names() -> None:
    facts = [_fact("capacity", "2000mAh", "mAh", image=4), _fact("capacity", "4000mAh", "mAh", image=9)]
    draft = _draft_with(_real_capture(BATTERY), facts)
    capacity = draft["specs"]["capacity"]
    assert capacity["status"] == "ok"
    assert capacity["value"] == "1300mAh / 1500mAh / 2000mAh / 2500mAh"
    assert capacity["per_variant"]["2000mah"] == "2000mAh" and "12V直充充电器" not in capacity["per_variant"]
    assert [a["value"] for a in capacity["alternatives"]] == ["4000"]  # 对不上任何规格的,列出来不标红
    by_name = {v["name_zh"]: v for v in draft["variants"]}
    assert by_name["1300mah"]["specs"]["capacity"] == "1300mAh" and by_name["1300mah"]["cost_price_cny"] == 16.99
    assert "capacity" not in by_name["12V直充充电器"]["specs"]


def test_dimension_drawing_labels_merge_and_part_labels_are_dropped() -> None:
    capture = {"attributes": [], "title_zh": "电池"}
    # 同一段里分开标的 40 / 48 / 84 mm → 一条 84×48×40;四个以上的单独标注是零件尺寸,不要。
    facts = [_fact("dimensions", v, "", image=10) for v in ("40mm", "48mm", "84mm")]
    facts += [_fact("dimensions", v, "MM", image=12) for v in ("35", "16", "140", "119")]
    stats: dict = {}
    specs, _ = dossier.merge_specs(capture, facts, stats=stats)
    dims = specs["dimensions"]
    assert dims["status"] == "ok" and dims["value"] == "84×48×40" and dims["unit"] == "mm"
    assert stats["ignored_drawing"] == 4
    # 同一段已有完整的长×宽×高,单个标注就是多余的
    facts = [_fact("dimensions", "153*40*40", "mm", image=13), _fact("dimensions", "35", "MM", image=13)]
    specs, _ = dossier.merge_specs(capture, facts, stats=(stats := {}))
    assert specs["dimensions"]["value"] == "153×40×40" and stats["ignored_drawing"] == 1
    # 页面属性里的 x 也统一成 ×,单位照常拆出来
    specs, _ = dossier.merge_specs({"attributes": [{"name": "尺寸", "value": "15x4x4cm", "source": "page_json"}]}, [])
    assert specs["dimensions"]["value"] == "15×4×4" and specs["dimensions"]["unit"] == "cm"


def test_value_in_another_unit_is_not_this_field() -> None:
    # 10-26 电钻(#9):广告图「续航持久」表盘上的 25% 被读成了续航,没标红就进了档案。
    draft = _draft_with(_real_capture(DRILL), [_fact("runtime", "25", "%", image=5), _fact("runtime", "25%", image=5, segment=1)])
    assert "runtime" not in draft["specs"]
    assert draft["image_read"]["ignored_unit"] == 2
    # 别的量的单位同理;认不出的单位(Wh)照收,宁可多列也不悄悄丢
    facts = [
        _fact("capacity", "12", "V", image=6),
        _fact("weight", "84", "mm", image=7),
        _fact("runtime", "3-5 小时", image=8),
        _fact("capacity", "18", "Wh", image=9),
    ]
    stats: dict = {}
    specs, _ = dossier.merge_specs({"attributes": [], "title_zh": "露营灯"}, facts, stats=stats)
    assert stats["ignored_unit"] == 2 and "weight" not in specs
    assert (specs["runtime"]["value"], specs["runtime"]["unit"]) == ("3-5", "小时")
    assert (specs["capacity"]["value"], specs["capacity"]["unit"]) == ("18", "Wh")


def test_quantity_without_a_number_is_a_slogan() -> None:
    # 10-26 电钻重新整理(#10):25% 拦住了,同一套图「核心卖点」拼图上的配字「电力强劲 持久续航」又被读成了续航。
    draft = _draft_with(_real_capture(DRILL), [_fact("runtime", "电力强劲 持久续航", image=2)])
    assert "runtime" not in draft["specs"]
    assert draft["image_read"]["ignored_narrative"] == 1
    # 只管量;材质这类文字字段本来就没有数,照收
    facts = [
        _fact("capacity", "大容量", image=3),
        _fact("weight", "轻便", image=4),
        _fact("runtime", "4小时", image=5),
        _fact("material", "阻燃ABS", image=6),
    ]
    stats: dict = {}
    specs, _ = dossier.merge_specs({"attributes": [], "title_zh": "露营灯"}, facts, stats=stats)
    assert stats["ignored_narrative"] == 2 and "capacity" not in specs and "weight" not in specs
    assert "runtime" in specs and specs["material"]["value"] == "阻燃ABS"


def test_title_vs_attribute_is_a_real_conflict_and_consult_service_is_a_placeholder() -> None:
    # 电钻:标题 12V,属性表「额定电压范围:交流220V」(充电器输入)—— 不替老板选;「外形尺寸:咨询客服」不是尺寸。
    draft = _draft_with(_real_capture(DRILL), [])
    voltage = draft["specs"]["voltage"]
    assert voltage["status"] == "conflict"
    assert {c["value"] for c in voltage["candidates"]} == {"交流220", "12"}
    assert draft["specs"]["dimensions"]["status"] == "missing" and "咨询客服" in draft["specs"]["dimensions"]["note"]
    assert dossier.is_placeholder("咨询客服") and dossier.is_placeholder("以实际为准") and not dossier.is_placeholder("尼龙+PS")


def test_strong_image_fact_conflicts_with_page_but_weak_one_is_only_listed() -> None:
    capture = {"attributes": [{"name": "材质", "value": "铝合金", "source": "page_json"}], "title_zh": "驱蚊露营灯"}
    strong, _ = dossier.merge_specs(capture, [_fact("material", "尼龙+PS", image=13)])
    assert strong["material"]["status"] == "conflict"
    assert [c["value"] for c in strong["material"]["candidates"]] == ["铝合金", "尼龙+PS"]
    weak, _ = dossier.merge_specs(capture, [_fact("material", "尼龙+PS", confidence="low", image=13)])
    assert weak["material"]["status"] == "ok" and weak["material"]["value"] == "铝合金"
    assert weak["material"]["alternatives"][0]["value"] == "尼龙+PS"
    unsure, _ = dossier.merge_specs(capture, [_fact("material", "尼龙+PS", subject="unsure", image=13)])
    assert unsure["material"]["status"] == "ok"


def test_same_value_written_differently_is_not_a_conflict() -> None:
    capture = {"attributes": [{"name": "重量", "value": "0.166kg", "source": "page_json"}], "title_zh": "电池"}
    facts = [
        _fact("weight", "166", "g", image=11, scope="item"),
        _fact("material", "ABS阻燃外壳", image=9),
        _fact("material", "阻燃ABS材料", image=11),
        _fact("voltage", "12V", "V", image=3),
        _fact("voltage", "12V V", "", image=11),
        _fact("cycle_life", "500", "次", image=6),
        _fact("cycle_life", "400-500", "次", image=7),
        _fact("cycle_life", "500+", "", image=11),
    ]
    specs, _ = dossier.merge_specs(capture, facts)
    for key in ("weight", "material", "voltage", "cycle_life"):
        assert specs[key]["status"] == "ok", (key, specs[key])
    assert specs["voltage"]["value"] == "12" and specs["voltage"]["unit"] == "V"


def test_union_fields_list_at_most_four_values() -> None:
    capture = {"attributes": [{"name": "产品认证", "value": "MSDS、ce、UN38.3", "source": "page_json"}], "title_zh": "电池"}
    facts = [_fact("certification", v, image=14) for v in ("CE", "UN38.3 Test Report", "EMC", "UL 1642", "FCC Part 15", "RoHS")]
    specs, _ = dossier.merge_specs(capture, facts)
    cert = specs["certification"]
    assert cert["status"] == "ok" and cert["value"].startswith("MSDS、ce、UN38.3")
    assert len(cert["value"].split("、")) == 3 + 3  # 页面那条本身带 3 个 + 另外 3 种
    assert [a["value"] for a in cert["alternatives"]] == ["RoHS"]
    assert all("UN38.3 Test Report" not in v for v in cert["value"].split("、"))  # 和页面的 UN38.3 是同一个


def test_color_from_bracketed_sku_names() -> None:
    capture = {"attributes": [{"name": "颜色", "value": "AH06光棍驱蚊露营灯[黑色]、AH06光棍驱蚊露营灯[绿色]", "source": "page_json"}]}
    specs, _ = dossier.merge_specs(capture, [])
    assert specs["color"]["value"] == "黑色、绿色"


def test_pricing_for_sku_priced_offer_and_retail_note() -> None:
    draft = _draft_with(_real_capture(BATTERY), [])
    assert draft["pricing"]["mode"] == "sku" and draft["pricing"]["range_cny"] == [9.0, 49.0]
    assert draft["pricing"]["text"] == "按规格 ¥9–¥49"
    assert "按规格 ¥9–¥49" in draft["fields"]["retail_price"]["note"]
    assert draft["price_tiers"] == []


def test_reading_problems_are_flagged_not_hidden() -> None:
    capture = {**_real_capture(DRILL), "detail_error": "详情图清单取了 3 次都没取到(TimeoutError)"}
    draft = _draft_with(capture, [])
    flag = next(f for f in draft["flagged"] if f["path"] == "detail_images")
    assert "取了 3 次" in flag["note"] and "重新整理" in flag["note"]
    budget = _draft_with(_real_capture(BATTERY), [], stopped_reason="budget", segments_seen=9)
    assert any(f["path"] == "detail_images" and "预算" in f["note"] for f in budget["flagged"])
    degraded = _draft_with(_real_capture(BATTERY), [], stopped_reason="degraded")
    assert any(f["path"] == "detail_images" and "额度" in f["note"] for f in degraded["flagged"])
    fine = _draft_with(_real_capture(BATTERY), [])
    assert not any(f["path"] == "detail_images" for f in fine["flagged"])
    assert all(f.get("label") for f in fine["flagged"])


def test_reading_text_on_card() -> None:
    assert dossiers.reading_text({"detail_error": "x"}) == "详情图没取到(规格只来自页面)"
    assert dossiers.reading_text({"images": 0}) == "卖家的详情里没有图片"
    text = dossiers.reading_text({"images": 11, "segments_seen": 16, "images_failed": 1, "stopped_reason": "budget"})
    assert text == "详情图 11 张,读了 16 段,1 张打不开(到单份预算上限停了)"


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("3-in-1 Outdoor Mosquito Repellent Camping Light with Flashlight and Tripod", "light"),
        ("Portable Camping Shower, 5 Gallon", "shower"),
        ("12V Lithium Battery for Cordless Drill and Screwdriver Power Tools", "battery"),
        ("Squishy Dumpling Stress Relief Toys (12 Pack)", "toy"),
        ("Glass Boxes", "box"),
        ("", None),
    ],
)
def test_head_noun(name: str, head: str | None) -> None:
    assert dossier.head_noun(name) == head


def test_precedent_needs_the_same_head_noun() -> None:
    # 10-26 灭蚊露营灯被照着店里的露营淋浴器判成了「便携淋浴」:英文名里都有 camping / outdoor。
    lamp = "3-in-1 Outdoor Mosquito Repellent Camping Light with Flashlight"
    showers = [("499", "Portable Camping Shower Outdoor", "SHW-001"), ("499", "Outdoor Camping Shower Bag", "SHW-002")]
    assert dossier.precedent_from_rows(lamp, showers) is None
    lights = [("2370", "Camping Lantern Light", "LGT-002"), ("2370", "LED Camping Light", "LGT-001")]
    assert dossier.precedent_from_rows(lamp, showers + lights) == ("2370", 2, "LGT-001")
    split = lights + [("9999", "Camping String Light", "LGT-003"), ("9999", "Tent Light", "LGT-004")]
    assert dossier.precedent_from_rows(lamp, split) is None  # 两个类目打平,不算先例
