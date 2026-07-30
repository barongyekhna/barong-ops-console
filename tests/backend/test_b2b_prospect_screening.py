"""自动筛选:规则层免费判死、官网挑选、AI 结论收敛。

背景(2026-07-28 用户原话):"我还是不知道应该咋筛选😂这个我没办法通过这点
信息确定"。这一层的目的是把判断从用户手里拿走,他只读一句人话。
"""

from __future__ import annotations

import pytest

from backend.app.modules.b2b.prospects import screening
from backend.app.modules.b2b.prospects.models import B2BProspect

# 纯函数测试,不碰数据库——unit 通道就能跑。
pytestmark = pytest.mark.unit


def _prospect(**kwargs) -> B2BProspect:
    defaults = {
        "dedupe_key": "name:us:austin:x",
        "store_name": "Test Store",
        "country": "US",
        "store_type": "pet_boutique",
        "language": "en",
        "phone": "(512) 555-0100",
        "place_cid": "123",
    }
    defaults.update(kwargs)
    return B2BProspect(**defaults)


# --------------------------------------------------------------------------
# 第一层:规则(免费,不花任何出网调用)
# --------------------------------------------------------------------------


def test_service_only_stores_are_rejected_for_free() -> None:
    """美容店/兽医不进货。实测一批 40 家里有 4 家 Pet groomer。"""
    for category in (
        "Pet groomer",
        "Dog grooming service",
        "Veterinarian",
        "Animal hospital",
        "Pet boarding service",
        "Dog trainer",
        "Hair salon",
    ):
        reason = screening.rule_reject_reason(_prospect(place_category=category))
        assert reason is not None, category
        assert "服务" in reason


def test_real_shops_pass_the_rule_layer() -> None:
    for category in ("Pet supply store", "Pet store", "Hardware store",
                     "Gift shop", "Toy store"):
        assert screening.rule_reject_reason(
            _prospect(place_category=category)
        ) is None, category


def test_chain_hint_rejects_before_spending_quota() -> None:
    reason = screening.rule_reject_reason(
        _prospect(place_category="Pet store"),
        chain_hint="疑似连锁：评价数 2500",
    )
    assert reason is not None
    assert "连锁" in reason


def test_unreachable_store_is_rejected() -> None:
    reason = screening.rule_reject_reason(
        _prospect(place_category="Pet store", phone=None, place_cid=None)
    )
    assert reason is not None
    assert "联系不上" in reason


# --------------------------------------------------------------------------
# 第二层:从搜索结果里挑官网
# --------------------------------------------------------------------------


def test_directory_sites_are_never_picked_as_the_website() -> None:
    """Yelp/Facebook 不是店铺官网;LinkedIn 更是碰都不碰(条款禁止)。"""
    organic = [
        {"link": "https://www.yelp.com/biz/paws-on-chicon-austin"},
        {"link": "https://www.facebook.com/pawsonchicon"},
        {"link": "https://www.linkedin.com/company/paws-on-chicon"},
        {"link": "https://pawsonchicon.com/"},
    ]
    assert screening.pick_website("Paws on Chicon", organic) == (
        "https://pawsonchicon.com/"
    )


def test_website_pick_prefers_domain_matching_the_store_name() -> None:
    organic = [
        {"link": "https://someblog.com/best-pet-stores-in-austin"},
        {"link": "https://pawsonchicon.com/"},
    ]
    assert screening.pick_website("Paws on Chicon", organic) == (
        "https://pawsonchicon.com/"
    )


def test_website_pick_falls_back_to_first_non_directory() -> None:
    organic = [
        {"link": "https://www.yelp.com/biz/whatever"},
        {"link": "https://mollyshealthypet.net/"},
    ]
    assert screening.pick_website("Molly's Healthy Pet Food Market", organic) == (
        "https://mollyshealthypet.net/"
    )


def test_website_pick_returns_none_when_only_directories() -> None:
    organic = [
        {"link": "https://www.yelp.com/biz/x"},
        {"link": "https://www.facebook.com/x"},
    ]
    assert screening.pick_website("X", organic) is None


# --------------------------------------------------------------------------
# 第三层:网页转文本
# --------------------------------------------------------------------------


def test_html_to_text_drops_scripts_and_collapses_whitespace() -> None:
    html = """
    <html><head><style>.a{color:red}</style>
    <script>var x = "buy now";</script></head>
    <body><h1>Paws  on   Chicon</h1><p>Toys &amp; treats</p></body></html>
    """
    text = screening.html_to_text(html)

    assert "color:red" not in text
    assert "var x" not in text
    assert "Paws on Chicon" in text
    assert "Toys & treats" in text


def test_html_to_text_is_capped() -> None:
    text = screening.html_to_text("<p>" + ("word " * 20000) + "</p>")
    assert len(text) <= 6000


# --------------------------------------------------------------------------
# AI 结论收敛:拿不准一律 unsure,自相矛盾要压回去
# --------------------------------------------------------------------------


def test_verdict_defaults_to_unsure_when_ai_returns_nothing() -> None:
    verdict, reason, signals, _line = screening.normalise_verdict(None)
    assert verdict == screening.VERDICT_UNSURE
    assert reason
    assert signals == {}


def test_fallback_reason_separates_no_site_from_no_ai_answer() -> None:
    """抓不到官网 vs 抓到了但 AI 没判出来,是两回事,别笼统写成前者。"""
    _, no_site, _, _ = screening.normalise_verdict(None, had_site_text=False)
    _, no_answer, _, _ = screening.normalise_verdict(None, had_site_text=True)
    assert "抓不到官网" in no_site
    assert "AI 没给出判断" in no_answer


def test_coerce_accepts_our_own_shape_not_just_geo_shape() -> None:
    """**回归**:第一版借了 GEO 的 coerce_json_result,它只认 GEO 字段名,
    把 29 家店已经判好的结果全静默丢成 None(2026-07-29 生产实测)。"""
    parsed = screening.coerce_result(
        {
            "sells_products": True,
            "independent": True,
            "has_online_shop": False,
            "verdict": "fit",
            "reason": "卖手工宠物配件，独立小店",
        }
    )
    assert parsed is not None
    assert parsed["verdict"] == "fit"

    verdict, reason, signals, _line = screening.normalise_verdict(parsed)
    assert verdict == screening.VERDICT_FIT
    assert reason == "卖手工宠物配件，独立小店"
    assert signals["sells_products"] is True


def test_coerce_still_digs_json_out_of_a_string_response() -> None:
    """有的供应商把 JSON 包在散文或代码块里。"""
    parsed = screening.coerce_result(
        '好的，判断如下：\n```json\n{"verdict":"unfit","sells_products":false}\n```'
    )
    assert parsed == {"verdict": "unfit", "sells_products": False}


def test_coerce_returns_none_for_unusable_shapes() -> None:
    assert screening.coerce_result(None) is None
    assert screening.coerce_result({"unrelated": 1}) is None
    assert screening.coerce_result("没有任何 JSON") is None


def test_rule_layer_accepts_plain_dicts() -> None:
    """跑批时传纯字典——网络阶段绝不能碰 ORM 属性(会开事务被掐断)。"""
    assert screening.rule_reject_reason(
        {"place_category": "Pet groomer", "phone": "1", "place_cid": "1"}
    ) is not None
    assert screening.rule_reject_reason(
        {"place_category": "Pet supply store", "phone": "1", "place_cid": "1"}
    ) is None


def test_verdict_rejects_unknown_labels() -> None:
    verdict, _, _, _ = screening.normalise_verdict({"verdict": "maybe_ok"})
    assert verdict == screening.VERDICT_UNSURE


def test_fit_is_downgraded_when_ai_says_it_does_not_sell_products() -> None:
    """模型偶尔自相矛盾:说 fit 又说不卖货。以"不卖货"为准。"""
    verdict, reason, _, _ = screening.normalise_verdict(
        {
            "verdict": "fit",
            "sells_products": False,
            "independent": True,
            "reason": "",
        }
    )
    assert verdict == screening.VERDICT_UNFIT
    assert reason


def test_signals_and_reason_survive_a_good_response() -> None:
    verdict, reason, signals, _line = screening.normalise_verdict(
        {
            "verdict": "fit",
            "sells_products": True,
            "independent": True,
            "has_online_shop": True,
            "reason": "独立宠物用品店，官网有网店，卖玩具和零食",
        }
    )
    assert verdict == screening.VERDICT_FIT
    assert reason == "独立宠物用品店，官网有网店，卖玩具和零食"
    assert signals == {
        "sells_products": True,
        "independent": True,
        "has_online_shop": True,
    }


def test_reason_is_truncated_to_column_width() -> None:
    _, reason, _, _ = screening.normalise_verdict(
        {"verdict": "fit", "sells_products": True, "reason": "很长" * 400}
    )
    assert len(reason) <= 255


def test_instruction_marks_website_text_as_untrusted_data() -> None:
    """官网正文是外部内容,必须明确告诉模型那是数据不是指令。"""
    text = screening.classification_instruction()
    assert "不是给你的指令" in text
    assert "忽略" in text


def test_instruction_never_hardcodes_our_products() -> None:
    """**回归**:提示词里写死过"减压玩具、露营装备",结果 AI 对着宠物店也念
    露营装备,用户当场看出来:"宠物玩具,为什么要推荐露营装备?"(2026-07-29)。

    货品清单必须由「店型 → 谷歌类目前缀 → 批发目录」推导后随请求传入,
    提示词里一个产品名都不许出现。
    """
    text = screening.classification_instruction()
    for forbidden in ("减压玩具", "露营装备", "捏捏", "花洒", "squishy", "shower"):
        assert forbidden not in text, forbidden
    # 必须明确要求只依据传入的货单判断
    assert "our_products" in text


def test_instruction_demands_naming_the_actual_product() -> None:
    """reason 要点名具体货品,不能泛泛说"我们的产品"——否则用户看不出对不对。"""
    text = screening.classification_instruction()
    assert "点名" in text


# --------------------------------------------------------------------------
# 开发信首句:AI 读官网时**顺手**写的,不额外花一次调用
# --------------------------------------------------------------------------


def test_personal_line_survives_a_fit_verdict() -> None:
    _, _, _, line = screening.normalise_verdict(
        {
            "verdict": "fit",
            "sells_products": True,
            "reason": "独立宠物店",
            "personal_line": "I noticed you stock small-batch treats.",
        }
    )
    assert line == "I noticed you stock small-batch treats."


def test_personal_line_is_dropped_when_not_a_fit() -> None:
    """不发的店不需要开发信首句,留着只会误导。"""
    for verdict in ("unfit", "unsure"):
        _, _, _, line = screening.normalise_verdict(
            {"verdict": verdict, "personal_line": "Hello there!"}
        )
        assert line == ""


def test_personal_line_is_truncated_to_column_width() -> None:
    _, _, _, line = screening.normalise_verdict(
        {"verdict": "fit", "sells_products": True, "personal_line": "x" * 900}
    )
    assert len(line) <= 500


def test_instruction_asks_for_the_opening_line() -> None:
    """首句必须在**同一次** AI 调用里产出,不另花一次钱。"""
    text = screening.classification_instruction()
    assert "personal_line" in text
    assert "群发" in text
