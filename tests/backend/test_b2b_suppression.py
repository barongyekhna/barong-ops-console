"""永不再发名单 + 合规落款。

**为什么这两件必须在第一封信之前做完**(2026-07-30):跟进模板里写着"回复
no thanks 我就不烦你了",但系统里没地方记——下一轮生成草稿还会给他生成。
一个说过"别发了"还继续收到信的人会直接点举报垃圾邮件,投诉率一高
barongsupply.com 就废了(用户红线:退信/投诉率 >3% 杀域名)。
"""

from __future__ import annotations

import pytest

from backend.app.modules.b2b.outreach import suppression
from backend.app.modules.b2b.outreach import templates_catalog as catalog

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# 地址归一化
# --------------------------------------------------------------------------


def test_normalise_folds_case_whitespace_and_plus_tags() -> None:
    """不归一的话,`Bob@Shop.com` 退订了 `bob@shop.com` 照样能收到。"""
    assert suppression.normalise("  Bob@Shop.COM ") == "bob@shop.com"
    assert suppression.normalise("bob+wholesale@gmail.com") == "bob@gmail.com"
    assert suppression.normalise("BOB+a+b@Gmail.com") == "bob@gmail.com"


def test_normalise_rejects_things_that_are_not_addresses() -> None:
    """空串永远不该匹配上任何人——否则整个名单会把所有人都挡住。"""
    for bad in (None, "", "   ", "notanemail", "@nolocal.com", "nodomain@"):
        assert suppression.normalise(bad) == ""


def test_empty_key_never_counts_as_suppressed() -> None:
    """没邮箱的候选不该被当成"在名单里"而被静默跳过。"""
    assert suppression.normalise("") == ""


# --------------------------------------------------------------------------
# 合规落款（CAN-SPAM）
# --------------------------------------------------------------------------


def test_cold_email_footer_carries_address_and_opt_out() -> None:
    """美国对商业邮件的硬要求:真实实体地址 + 可用的退订方式。"""
    from backend.app.modules.b2b import policies

    footer = catalog.compliance_footer("en")
    assert policies.LEGAL_ENTITY in footer
    for line in policies.ADDRESS_LINES:
        assert line in footer
    assert "unsubscribe" in footer.lower()


def test_footer_address_is_not_a_second_copy() -> None:
    """地址从 policies.py 取,不在模板目录里抄第二份——两处对不上就是
    GMC 判口径不一致的老病。"""
    from pathlib import Path

    source = Path(catalog.__file__).read_text(encoding="utf-8")
    body = source[source.index("def compliance_footer(") :]
    assert "policies.ADDRESS_LINES" in body
    assert "policies.LEGAL_ENTITY" in body
    assert "Guangzhou" not in body, "地址被抄了第二份"


def test_footer_is_appended_only_to_cold_kinds() -> None:
    """对方主动来问价,再附一句"回复 unsubscribe 退订"很怪——那是往来通信,
    不是推销。"""
    assert catalog.KIND_FIRST_TOUCH in catalog.KIND_REQUIRES_FOOTER
    assert catalog.KIND_FOLLOW_UP in catalog.KIND_REQUIRES_FOOTER
    for kind in (
        catalog.KIND_REPLY_PRICING,
        catalog.KIND_REPLY_MOQ,
        catalog.KIND_REPLY_SAMPLE,
        catalog.KIND_REPLY_OEM,
        catalog.KIND_REPLY_NO,
    ):
        assert kind not in catalog.KIND_REQUIRES_FOOTER
        assert catalog.with_compliance_footer("body", kind=kind) == "body"


def test_footer_is_not_appended_twice() -> None:
    once = catalog.with_compliance_footer(
        "Hi", kind=catalog.KIND_FIRST_TOUCH
    )
    twice = catalog.with_compliance_footer(
        once, kind=catalog.KIND_FIRST_TOUCH
    )
    assert once == twice


def test_footer_speaks_the_recipients_language() -> None:
    assert "unsubscribe" in catalog.compliance_footer("es").lower()
    assert "No le interesa" in catalog.compliance_footer("es")


def test_footer_lives_outside_the_editable_template_body() -> None:
    """**法律要求的东西不该能被"改模板"删掉。** 落款在渲染草稿时追加,
    所以模板正文里不许出现它。"""
    for spec in catalog.TEMPLATE_CATALOG:
        assert "unsubscribe" not in spec["body"].lower()


def test_footer_never_trips_the_payment_red_line() -> None:
    """落款也要过支付红线校验:B2B 只收电汇。"""
    for language in ("en", "es"):
        assert catalog.forbidden_phrase_in(catalog.compliance_footer(language)) is None


# --------------------------------------------------------------------------
# 生成草稿时必须真的挡住
# --------------------------------------------------------------------------


def test_draft_generation_checks_the_suppression_list() -> None:
    """光有名单不算数,生成草稿那条路上必须真的查。"""
    from pathlib import Path

    import backend.app.modules.b2b.outreach.service as svc

    source = Path(svc.__file__).read_text(encoding="utf-8")
    body = source[source.index("def generate_drafts(") :]
    assert "suppression.suppressed_set(db)" in body, "没取名单"
    assert "suppression.normalise(prospect.email) in blocked" in body, "没比对"
    # 落款也必须在这条路上加上
    assert "with_compliance_footer" in body


def test_suppression_list_is_fetched_once_not_per_prospect() -> None:
    """逐条查库在 100 个候选上就是 100 次往返。"""
    from pathlib import Path

    import backend.app.modules.b2b.outreach.service as svc

    body = Path(svc.__file__).read_text(encoding="utf-8")
    body = body[body.index("def generate_drafts(") :]
    assert body.count("suppressed_set(") == 1
    assert "is_suppressed(" not in body


def test_suppression_is_by_full_address_never_by_domain() -> None:
    """**用户 2026-07-30 提的**:很多小店老板用的就是 gmail / outlook,不是每个人
    都有自己域名的邮箱。

    只要有一处按域名匹配,一个 gmail 用户退订就会连坐掉**所有** gmail 的候选
    ——名单会悄悄把大半个客户池吃掉,而且看不出来(草稿数变少不会报错)。
    """
    same_domain = ("bob@gmail.com", "sarah@gmail.com", "store@gmail.com")
    keys = {suppression.normalise(e) for e in same_domain}
    assert len(keys) == 3, "同域名的不同人被折叠成了同一个键"

    # 归一化必须保留 @ 两边:退化成只剩域名就是灾难
    for email in same_domain + ("owner@outlook.com", "hi@myshop.com"):
        key = suppression.normalise(email)
        local, _, domain = key.partition("@")
        assert local, f"{email} 归一化后丢了用户名"
        assert domain, f"{email} 归一化后丢了域名"


def test_suppression_code_has_no_domain_level_matching() -> None:
    """源码级守卫:以后谁想加"按域名拉黑"必须先改掉这条测试,顺便读到上面的理由。"""
    from pathlib import Path

    source = Path(suppression.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in ("endswith(\"@", "endswith('@", "domain ==", "by_domain", "split(\"@\")[1]"):
        assert banned not in lowered, f"出现了按域名匹配的痕迹: {banned}"
