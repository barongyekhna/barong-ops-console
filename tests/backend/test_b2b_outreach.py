"""开发信:邮箱抓取、模板红线、渲染、草稿箱只生成不发送。

背景(2026-07-29 用户问"店爬出来了,然后呢?怎么发信?模板有哪些?")。
"""

from __future__ import annotations

import pytest

from backend.app.modules.b2b.outreach import email_finder
from backend.app.modules.b2b.outreach import templates_catalog as catalog

# 纯函数,unit 通道就能跑。
pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# 邮箱抓取
# --------------------------------------------------------------------------


def test_emails_come_from_raw_html_including_mailto() -> None:
    """**回归**:第一版拿剥完标签的纯文本捞,`<a href="mailto:...">` 里的邮箱
    连同 href 一起没了,实测 6 家店只捞到 1 家(2026-07-29)。"""
    html = '<a href="mailto:hello@barknpurr.com">Contact Us</a>'
    assert email_finder.emails_from_html(html) == ["hello@barknpurr.com"]


def test_url_encoded_mailto_is_decoded() -> None:
    """**回归**:href 里常写成 "mailto:%20shop@x.com",不解码就存成
    "%20shop@x.com" —— 一个发不出去的地址。死规矩:绝不往不存在的地址发信。
    (2026-07-29 实测 Zamzows 中招。)"""
    assert email_finder.emails_from_html(
        '<a href="mailto:%20zamzows@zamzows.com">Email us</a>'
    ) == ["zamzows@zamzows.com"]
    assert email_finder.emails_from_html(
        '<a href="mailto:hello%40realshop.com">Email</a>'
    ) == ["hello@realshop.com"]


def test_whitespace_inside_mailto_is_stripped() -> None:
    assert email_finder.emails_from_html(
        '<a href="mailto: shop@x.com ">Email</a>'
    ) == ["shop@x.com"]


def test_obfuscated_addresses_are_recovered() -> None:
    """小店常用 "info [at] shop [dot] com" 这种反爬写法。"""
    html = "<p>write to info [at] barknpurr [dot] com</p>"
    assert email_finder.emails_from_html(html) == ["info@barknpurr.com"]


def test_platform_and_image_noise_is_dropped() -> None:
    html = """
    noreply@shopify.com sentry@sentry.io logo@2x.png hero@image.jpeg
    someone@example.com postmaster@realshop.com hello@realshop.com
    """
    assert email_finder.emails_from_html(html) == ["hello@realshop.com"]


def test_same_domain_address_wins() -> None:
    """店自己的信箱优先于他家用的第三方/私人邮箱。"""
    emails = ["ownerpersonal@gmail.com", "info@urbantailspet.com"]
    assert email_finder.pick_best_email(emails, "https://urbantailspet.com/") == (
        "info@urbantailspet.com"
    )


def test_preferred_local_parts_are_ranked() -> None:
    emails = ["careers@shop.com", "hello@shop.com", "random@shop.com"]
    assert email_finder.pick_best_email(emails, "https://shop.com") == (
        "hello@shop.com"
    )


def test_no_email_is_not_an_error() -> None:
    assert email_finder.pick_best_email([], "https://shop.com") is None
    assert email_finder.find_email_on_site(None) == (None, None)


def test_linkedin_is_never_in_the_contact_paths() -> None:
    """死规矩:LinkedIn 条款禁止爬取,碰都不碰。"""
    joined = " ".join(email_finder.CONTACT_PATHS)
    assert "linkedin" not in joined.lower()


# --------------------------------------------------------------------------
# 模板红线
# --------------------------------------------------------------------------


def test_no_builtin_template_mentions_card_payment() -> None:
    """用户死命令:B2B 只收电汇。收到货再来一手拒付就完蛋了。"""
    for spec in catalog.TEMPLATE_CATALOG:
        combined = f"{spec['subject']}\n{spec['body']}"
        assert catalog.forbidden_phrase_in(combined) is None, spec["kind"]


def test_forbidden_phrase_detector_catches_card_wording() -> None:
    assert catalog.forbidden_phrase_in("We accept credit card") == "credit card"
    assert catalog.forbidden_phrase_in("PayPal is fine") == "paypal"
    assert catalog.forbidden_phrase_in("可以刷信用卡") == "信用卡"
    assert catalog.forbidden_phrase_in("Bank transfer only") is None


def test_first_touch_never_mentions_an_attachment() -> None:
    """首封带附件直接进垃圾箱,图册只在"要价格表"那封回复里发。"""
    for spec in catalog.TEMPLATE_CATALOG:
        if spec["kind"] != catalog.KIND_FIRST_TOUCH:
            continue
        body = spec["body"].lower()
        for word in ("attach", "catalog", "line sheet", "adjunto", "catálogo"):
            assert word not in body, f"{spec['language']}: {word}"


def test_pricing_reply_states_sea_freight_only() -> None:
    """免运费仅限海运。漏了这四个字,客户走 UPS 红单能把人赔垮。"""
    spec = next(
        s for s in catalog.TEMPLATE_CATALOG
        if s["kind"] == catalog.KIND_REPLY_PRICING
    )
    body = spec["body"].lower()
    assert "sea freight only" in body
    assert "ups" in body and "paid by the buyer" in body


def test_sample_wording_is_charged_then_credited() -> None:
    """样品**收费**、首单全额抵扣。用户纠正过一次口径,别写成免费。"""
    for kind in (catalog.KIND_FIRST_TOUCH, catalog.KIND_REPLY_SAMPLE):
        for spec in catalog.TEMPLATE_CATALOG:
            if spec["kind"] != kind or spec["language"] != "en":
                continue
            body = spec["body"].lower()
            # 收费:两种说法都行
            assert "aren't free" in body or "is charged" in body
            # 抵扣:认语义不认字面("credit" 或 "comes off your first")
            assert "credit" in body or "comes off your first" in body


def test_every_kind_has_at_least_one_builtin_template() -> None:
    kinds = {spec["kind"] for spec in catalog.TEMPLATE_CATALOG}
    assert kinds == set(catalog.KIND_LABELS)


def test_only_first_touch_is_store_type_scoped() -> None:
    """跟进信和 5 个回复模板全店型共用——店型涨到 24 个也不是 24 套模板。"""
    assert catalog.STORE_TYPE_SCOPED_KINDS == (catalog.KIND_FIRST_TOUCH,)


def test_templates_only_use_known_placeholders() -> None:
    """写错占位符会原样发出去,买家看到 {store_nmae} 就完了。"""
    import re

    for spec in catalog.TEMPLATE_CATALOG:
        for token in re.findall(r"\{[a-z_]+\}", spec["subject"] + spec["body"]):
            assert token in catalog.PLACEHOLDERS, f"{spec['kind']}: {token}"
