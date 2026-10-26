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


class _StubRouter:
    def __init__(self, useful: list[bool]) -> None:
        self.useful = list(useful)
        self.calls: list[tuple[str, str]] = []

    def execute(self, *, provider, task_type, payload, org, module_id, usage_label):
        assert usage_label == "suqinghe" and module_id == "k.product_knowledge"
        content = payload["messages"][0]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        self.calls.append((provider, task_type))
        if provider == "fast":
            return {"useful": self.useful.pop(0) if self.useful else False, "kind": "specs"}
        return {"content": '```json\n{"facts":[{"field":"weight","value":"200","unit":"g","raw_text":"重量200g","confidence":"high"},{"field":"bogus","value":"x","unit":"","raw_text":"x","confidence":"weird"},{"field":"material","value":"","unit":""}]}\n```'}


def _capture_with(images: int) -> s.Capture:
    return s.Capture(offer_id="1", url=URL, detail_images=[f"https://cbu01.alicdn.com/img/ibank/{i}.jpg" for i in range(images)])


def test_read_detail_images_triages_then_extracts() -> None:
    router = _StubRouter([False, True, True])
    out = s.read_detail_images(
        None,
        _capture_with(3),
        download=lambda url: _image(800, 600),
        router_factory=lambda db: router,
    )
    assert out["segments_seen"] == 3 and out["segments_read"] == 2
    assert [p for p, _ in router.calls] == ["fast", "fast", "judge", "fast", "judge"]
    weights = [f for f in out["facts"] if f["field"] == "weight"]
    assert [(f["image_index"], f["segment_index"]) for f in weights] == [(1, 0), (2, 0)]
    # 未知字段归到 other,置信度不认识就记 low,空值丢掉。
    others = [f for f in out["facts"] if f["field"] == "other"]
    assert others and all(f["confidence"] == "low" for f in others)
    assert not any(f["field"] == "material" for f in out["facts"])
    assert out["stopped_reason"] is None


def test_read_detail_images_accepts_stored_dict() -> None:
    # 10-26 真链接首跑:dossiers 把 capture 存成 to_dict() 字典再交给读图,读图按属性取 → AttributeError。
    router = _StubRouter([False, True, True])
    out = s.read_detail_images(
        None,
        _capture_with(3).to_dict(),
        download=lambda url: _image(800, 600),
        router_factory=lambda db: router,
    )
    assert out["segments_seen"] == 3 and out["segments_read"] == 2


def test_read_detail_images_stops_at_budget() -> None:
    router = _StubRouter([True] * 20)
    out = s.read_detail_images(
        None,
        _capture_with(20),
        budget_usd=0.12,
        download=lambda url: _image(800, 600),
        router_factory=lambda db: router,
    )
    assert out["stopped_reason"] == "budget"
    assert out["cost_usd"] <= 0.12
    assert out["segments_read"] == 2


def test_read_detail_images_skips_failed_downloads() -> None:
    router = _StubRouter([True])
    out = s.read_detail_images(
        None,
        _capture_with(2),
        download=lambda url: None if url.endswith("0.jpg") else _image(500, 500),
        router_factory=lambda db: router,
    )
    assert out["segments_seen"] == 1 and out["facts"][0]["image_index"] == 1


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
