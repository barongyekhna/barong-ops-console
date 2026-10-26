"""苏青禾 1688 抓取段:链接解析、页面数据抽取、拦截判断、长图切段、看图预算。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from backend.app.modules.agent_series.suqinghe import sourcing_1688 as s

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "sqh1688" / "offer_1057528621016"
URL = "https://detail.1688.com/offer/1057528621016.html?spm=a2615&from=linkplus"


@pytest.fixture(scope="module")
def capture() -> s.Capture:
    return s.parse_capture(
        url=URL,
        html=FIXTURE.with_suffix(".html").read_text(encoding="utf-8"),
        text=FIXTURE.with_suffix(".txt").read_text(encoding="utf-8"),
        desc_js=FIXTURE.with_suffix(".desc.txt").read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://detail.1688.com/offer/1057528621016.html", "1057528621016"),
        (URL, "1057528621016"),
        ("detail.1688.com/offer/547072834783.html", "547072834783"),
        ("https://m.1688.com/offer/547072834783.html?a=1", "547072834783"),
        ("https://detail.m.1688.com/page/index.html?offerId=547072834783", "547072834783"),
        ("https://show.1688.com/x?id=1057528621016", "1057528621016"),
        ("https://www.amazon.com/dp/B000/offer/123456789", None),
        ("https://detail.1688.com.evil.com/offer/1057528621016.html", None),
        ("https://login.1688.com/member/signin.htm?Done=https://detail.1688.com/offer/1057528621016.html", None),
        ("https://detail.1688.com/punish?x5secdata=1&offer/1057528621016", None),
        ("", None),
        ("https://detail.1688.com/offer/abc.html", None),
    ],
)
def test_parse_offer_id(url: str, expected: str | None) -> None:
    assert s.parse_offer_id(url) == expected


def test_parse_capture_reads_page_data(capture: s.Capture) -> None:
    assert capture.offer_id == "1057528621016"
    assert "捏捏乐" in (capture.title_zh or "")
    assert capture.category_zh == "减压玩具"
    assert capture.supplier["name"] == "义乌市多加玩具有限公司"
    assert capture.supplier["years"] == 4
    assert capture.unit == "个"
    assert capture.moq == 12
    assert capture.sold_count == 1608
    assert [(t["min_qty"], t["price_cny"]) for t in capture.price_tiers] == [(12, 3.30), (24, 2.90), (144, 2.70)]


def test_parse_capture_skus_merge_weight_and_images(capture: s.Capture) -> None:
    assert len(capture.skus) >= 16
    assert all(sku["name"] for sku in capture.skus)
    first = capture.skus[0]
    assert first["weight_g"] == 200
    assert first["sku_id"] == "6264069311391"
    # 1688 用 0 表示没填:长宽高是 0,必须变成 None,不能当成真的 0 厘米。
    assert first["length_cm"] is None and first["height_cm"] is None
    assert first["image_url"].startswith("https://cbu01.alicdn.com/img/ibank/")
    # skuMap 的 priceAmount 含义不明,不当价格。
    assert first["price_cny"] is None
    assert capture.sku_props and capture.sku_props[0]["prop"] == "规格"


def test_parse_capture_attributes_and_images(capture: s.Capture) -> None:
    attrs = {a["name"]: a["value"] for a in capture.attributes}
    assert attrs["适用年龄"] == "青年（15-35岁）"
    assert attrs["包装"] == "盒装"
    assert all(a["source"] == "page_json" for a in capture.attributes)
    assert capture.gallery_images
    assert all(not u.endswith((".webp", "_sum.jpg")) or u.endswith("cib.webp") for u in capture.gallery_images)
    assert len(capture.gallery_images) == len(set(capture.gallery_images))
    assert len(capture.detail_images) == 9
    assert capture.detail_url and capture.detail_url.startswith("https://itemcdn.tmall.com/1688offer/")
    assert capture.to_dict()["offer_id"] == "1057528621016"


def test_text_fallback_when_no_page_json() -> None:
    text = FIXTURE.with_suffix(".txt").read_text(encoding="utf-8")
    capture = s.parse_capture(url=URL, html="<html></html>", text=text, desc_js=None)
    attrs = {a["name"]: a["value"] for a in capture.attributes}
    assert attrs.get("适用年龄") == "青年（15-35岁）"
    assert all(a["source"] == "page_text" for a in capture.attributes)
    assert capture.skus == [] and capture.detail_images == []


def test_normalize_image_url() -> None:
    assert s.normalize_image_url("//cbu01.alicdn.com/img/ibank/a.jpg_.webp") == "https://cbu01.alicdn.com/img/ibank/a.jpg"
    assert s.normalize_image_url("http://cbu01.alicdn.com/img/ibank/a.jpg_sum.jpg") == "https://cbu01.alicdn.com/img/ibank/a.jpg"
    assert s.normalize_image_url("https://cbu01.alicdn.com/img/ibank/a.png_310x310.jpg") == "https://cbu01.alicdn.com/img/ibank/a.png"


def test_detect_blocked() -> None:
    html = FIXTURE.with_suffix(".html").read_text(encoding="utf-8")
    good = "https://detail.1688.com/offer/1057528621016.html"
    # 正常页面里本来就有 login.taobao / baxia 字样,不能误判。
    assert "login.taobao" in html and "baxia" in html
    assert s.detect_blocked(final_url=good, title="捏捏乐 - 阿里巴巴", html=html) is None
    assert s.detect_blocked(
        final_url="https://login.1688.com/member/signin.htm?Done=x", title="登录", html="<html></html>"
    ).startswith("redirected:")
    assert s.detect_blocked(
        final_url="https://detail.1688.com/offer/1057528621016.html/_____tmd_____/punish?x5secdata=1",
        title="",
        html="",
    ).startswith("redirected:")
    assert s.detect_blocked(final_url=good, title="安全验证", html=html).startswith("title:")
    assert s.detect_blocked(final_url=good, title="捏捏乐", html="<div id='nc_1_n1z'>滑动验证</div>") == "captcha_page"
    assert s.detect_blocked(final_url=good, title="捏捏乐", html="<html>empty</html>") == "no_product_data"


def _image(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def test_slice_image_small_is_single_segment() -> None:
    segments = s.slice_image(_image(800, 600))
    assert len(segments) == 1
    assert Image.open(io.BytesIO(segments[0])).size == (800, 600)


def test_slice_image_tall_cuts_with_overlap_and_resizes() -> None:
    # 1580 宽 → 缩到 1000,高 6320 → 4000;步长 1100-80=1020 → 顶边 0,1020,2040,3060
    segments = s.slice_image(_image(1580, 6320))
    sizes = [Image.open(io.BytesIO(seg)).size for seg in segments]
    assert len(segments) == 4
    assert all(width == 1000 for width, _ in sizes)
    assert sizes[0][1] == 1100 and sizes[-1][1] == 4000 - 3060


def test_slice_image_respects_max_segments() -> None:
    assert len(s.slice_image(_image(1000, 60000), max_segments=24)) == 24


_FACTS_REPLY = (
    '```json\n{"facts":[{"field":"weight","value":"200","unit":"g","raw_text":"重量200g","subject":"this","confidence":"high"},'
    '{"field":"bogus","value":"x","unit":"","raw_text":"x","confidence":"weird"},{"field":"material","value":"","unit":""},'
    '{"field":"voltage","value":"18V","unit":"V","raw_text":"18V","subject":"other","variant":"","confidence":"high"}]}\n```'
)


class _StubRouter:
    """分拣和抄录按提示词区分(读图档可以是任何一档);degraded_after = 第几次调用起回降级标记。"""

    def __init__(self, useful: list[bool], *, degraded_after: int | None = None) -> None:
        self.useful = list(useful)
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[str] = []
        self.degraded_after = degraded_after

    def execute(self, *, provider, task_type, payload, org, module_id, usage_label):
        assert usage_label == "suqinghe" and module_id == "k.product_knowledge"
        content = payload["messages"][0]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        self.calls.append((provider, task_type))
        self.prompts.append(content[0]["text"])
        if self.degraded_after is not None and len(self.calls) > self.degraded_after:
            return {"content": '{"facts": []}', "_ai_degraded": True}
        if content[0]["text"] == s._TRIAGE_PROMPT:
            return {"useful": self.useful.pop(0) if self.useful else False, "kind": "specs"}
        return {"content": _FACTS_REPLY}


def _capture_with(images: int) -> s.Capture:
    return s.Capture(offer_id="1", url=URL, detail_images=[f"https://cbu01.alicdn.com/img/ibank/{i}.jpg" for i in range(images)])


def test_read_detail_images_triages_then_extracts_when_reader_is_expensive() -> None:
    router = _StubRouter([False, True, True])
    out = s.read_detail_images(
        None,
        _capture_with(3),
        download=lambda url: _image(800, 600),
        router_factory=lambda db: router,
        reader_role="judge",
    )
    assert out["segments_seen"] == 3 and out["segments_read"] == 2 and out["triage"] is True
    assert [p for p, _ in router.calls] == ["fast", "fast", "judge", "fast", "judge"]
    weights = [f for f in out["facts"] if f["field"] == "weight"]
    assert [(f["image_index"], f["segment_index"]) for f in weights] == [(1, 0), (2, 0)]
    # 未知字段归到 other,置信度不认识就记 low,空值丢掉;subject 照抄,没给就是 unsure。
    others = [f for f in out["facts"] if f["field"] == "other"]
    assert others and all(f["confidence"] == "low" and f["subject"] == "unsure" for f in others)
    assert not any(f["field"] == "material" for f in out["facts"])
    assert {f["subject"] for f in out["facts"] if f["field"] == "voltage"} == {"other"}
    assert out["stopped_reason"] is None


def test_read_detail_images_default_reader_is_haiku_reading_every_segment(monkeypatch) -> None:
    monkeypatch.delenv("SQH_1688_READER_ROLE", raising=False)
    monkeypatch.delenv("SQH_1688_TRIAGE", raising=False)
    router = _StubRouter([])
    out = s.read_detail_images(None, _capture_with(3), download=lambda url: _image(800, 600), router_factory=lambda db: router)
    assert [p for p, _ in router.calls] == ["fast", "fast", "fast"]
    assert out["reader_role"] == "fast" and out["triage"] is False and out["segments_read"] == 3
    assert all(prompt != s._TRIAGE_PROMPT for prompt in router.prompts)


def test_reader_settings_env(monkeypatch) -> None:
    monkeypatch.delenv("SQH_1688_READER_ROLE", raising=False)
    monkeypatch.delenv("SQH_1688_TRIAGE", raising=False)
    assert s.reader_settings() == ("fast", False)
    monkeypatch.setenv("SQH_1688_READER_ROLE", "judge")
    assert s.reader_settings() == ("judge", True)
    monkeypatch.setenv("SQH_1688_TRIAGE", "off")
    assert s.reader_settings() == ("judge", False)


def test_read_detail_images_accepts_stored_dict() -> None:
    # 10-26 真链接首跑:dossiers 把 capture 存成 to_dict() 字典再交给读图,读图按属性取 → AttributeError。
    router = _StubRouter([False, True, True])
    out = s.read_detail_images(
        None,
        _capture_with(3).to_dict(),
        download=lambda url: _image(800, 600),
        router_factory=lambda db: router,
        reader_role="judge",
    )
    assert out["segments_seen"] == 3 and out["segments_read"] == 2


def test_read_detail_images_budget_uses_real_spend_from_meter() -> None:
    # 预算闸看台账实数:10-26 之前按 $0.05/次 估,实际只有 1/3,读到 9/17 段就被自己的估算撞停。
    readings = [0.0, 0.1, 0.2, 0.5]

    def meter() -> float:
        return readings.pop(0) if len(readings) > 1 else readings[0]

    router = _StubRouter([])
    out = s.read_detail_images(
        None, _capture_with(20), budget_usd=0.5, download=lambda url: _image(800, 600),
        router_factory=lambda db: router, meter=meter, reader_role="fast",
    )
    assert out["stopped_reason"] == "budget" and out["segments_seen"] == 3
    assert out["cost_basis"] == "ledger" and out["cost_usd"] == 0.5


def test_read_detail_images_falls_back_to_estimate_without_ledger() -> None:
    router = _StubRouter([True] * 40)
    out = s.read_detail_images(
        None, _capture_with(40), budget_usd=0.12, download=lambda url: _image(800, 600),
        router_factory=lambda db: router, reader_role="judge",
    )
    assert out["stopped_reason"] == "budget" and out["cost_basis"] == "estimate"
    assert out["cost_usd"] <= 0.12 and out["segments_read"] == 5


def test_read_detail_images_stops_when_claude_is_degraded() -> None:
    # Claude 当天额度用完会被降级给 DeepSeek —— 降级档读不了图,读出来的不能当事实。
    router = _StubRouter([], degraded_after=1)
    out = s.read_detail_images(
        None, _capture_with(4), download=lambda url: _image(800, 600), router_factory=lambda db: router, reader_role="fast",
    )
    assert out["stopped_reason"] == "degraded" and out["segments_read"] == 1
    assert len([f for f in out["facts"] if f["field"] == "weight"]) == 1


def test_read_detail_images_counts_failed_downloads() -> None:
    router = _StubRouter([True])
    out = s.read_detail_images(
        None,
        _capture_with(2),
        download=lambda url: None if url.endswith("0.jpg") else _image(500, 500),
        router_factory=lambda db: router,
        reader_role="judge",
    )
    assert out["segments_seen"] == 1 and out["facts"][0]["image_index"] == 1
    assert out["images_failed"] == 1


def test_download_image_rejects_foreign_hosts() -> None:
    assert s.download_image("https://evil.example.com/a.jpg") is None


def test_multi_dimension_sku_matches_image_and_weight_by_id() -> None:
    import json as _json

    context = {
        "result": {
            "data": {
                "productPackInfo": {
                    "fields": {
                        "pieceWeightScale": {
                            "pieceWeightScaleInfo": [
                                {"sku1": "灰色猫咪", "sku2": "不含磁贴", "weight": 35, "length": 5.5, "width": 0, "height": 0, "skuId": 111}
                            ]
                        }
                    }
                }
            },
            "global": {
                "globalData": {
                    "model": {
                        "offerDetail": {
                            "offerId": 547072834783,
                            "subject": "猫咪冰箱贴",
                            "skuProps": [
                                {"prop": "颜色", "value": [{"name": "灰色猫咪", "imageUrl": "https://cbu01.alicdn.com/img/ibank/cat.jpg_.webp"}]},
                                {"prop": "款式", "value": [{"name": "不含磁贴"}]},
                            ],
                        },
                        "tradeModel": {"skuMap": [{"specAttrs": "灰色猫咪&gt;不含磁贴", "skuId": 111, "canBookCount": 5}], "unit": "件"},
                    }
                }
            },
        }
    }
    html = "<script>window.context=(function(b,d){return d})(window.contextPath," + _json.dumps(context, ensure_ascii=False) + ");</script>"
    capture = s.parse_capture(url="https://detail.1688.com/offer/547072834783.html", html=html, text="", desc_js=None)
    sku = capture.skus[0]
    assert sku["name"] == "灰色猫咪>不含磁贴"
    assert sku["image_url"] == "https://cbu01.alicdn.com/img/ibank/cat.jpg"
    assert sku["weight_g"] == 35 and sku["length_cm"] == 5.5 and sku["width_cm"] is None


# ---------------------------------------------------------------- 10-26 真链接:按规格定价、读图背景、详情描述重试

BATTERY = Path(__file__).parent / "fixtures" / "sqh1688" / "offer_643348607768"
DRILL = Path(__file__).parent / "fixtures" / "sqh1688" / "offer_888786557113"


def _parse(base: Path) -> s.Capture:
    offer = base.name.split("_")[1]
    text = base.with_suffix(".txt")
    return s.parse_capture(
        url=f"https://detail.1688.com/offer/{offer}.html",
        html=base.with_suffix(".html").read_text(encoding="utf-8"),
        text=text.read_text(encoding="utf-8") if text.exists() else "",
        desc_js=base.with_suffix(".desc.txt").read_text(encoding="utf-8"),
    )


def test_sku_priced_offer_reads_each_sku_price_and_has_no_fake_tiers() -> None:
    # 按规格定价:页面上那两个价(¥9 / ¥49)是最低—最高,不是阶梯。之前只留下了一个 ¥9。
    battery = _parse(BATTERY)
    assert battery.price_mode == "sku"
    assert {sku["name"]: sku["price_cny"] for sku in battery.skus} == {
        "2000mah": 39.0, "12V直充充电器": 9.0, "2500mah": 49.0, "1500mah": 29.0, "1300mah": 16.99,
    }
    assert battery.price_tiers == [] and battery.price_range == [9.0, 49.0] and battery.moq == 3
    assert len(battery.detail_images) == 19

    drill = _parse(DRILL)
    assert drill.price_mode == "sku" and drill.price_tiers == []
    assert {sku["name"]: sku["price_cny"] for sku in drill.skus} == {"两电一充套装": 76.0, "裸机": 36.0, "一电一充套装": 66.0}
    assert drill.moq == 1 and drill.supplier.get("years")


def test_range_priced_offer_keeps_tiers(capture: s.Capture) -> None:
    assert capture.price_mode == "range"
    assert capture.price_range == [] and len(capture.price_tiers) == 3
    assert all(sku["price_cny"] is None for sku in capture.skus)  # 阶梯价商品:规格不单独定价


def test_extract_prompt_tells_the_model_what_this_product_is() -> None:
    prompt = s.extract_prompt(_parse(BATTERY).to_dict())
    assert "12v手电钻电池" in prompt and "2000mah" in prompt and "12V直充充电器" in prompt
    assert "产品认证:MSDS、ce、UN38.3" in prompt
    assert "subject" in prompt and "other" in prompt and "兼容机型" in prompt


def test_fetch_detail_description_retries_then_says_why() -> None:
    calls: list[str] = []

    def flaky(url: str) -> str:
        calls.append(url)
        if len(calls) < 2:
            raise TimeoutError("timed out")
        return "var offer_details={}"

    assert s.fetch_detail_description("u", get=flaky, sleep=lambda _: None) == ("var offer_details={}", None)

    def down(url: str) -> str:
        raise TimeoutError("timed out")

    desc, error = s.fetch_detail_description("u", get=down, sleep=lambda _: None, attempts=3)
    assert desc is None and "3 次" in error and "TimeoutError" in error
