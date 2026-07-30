"""形式发票(PI):漏斗最后一节。

**为什么必须有这张纸**:外贸收钱的动作是买家拿着 PI 去银行电汇定金。没有它,
客户说"我要了"之后就卡住——之前整条链在这里是断的。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


def _doc(**overrides):
    base = dict(
        doc_type="proforma_invoice",
        stage="quoted",
        source_document_id=None,
        carton_count=None,
        gross_weight_kg=None,
        net_weight_kg=None,
        sample_credit=None,
        number="PI-20260730-001",
        issued_on=date(2026, 7, 30),
        valid_until=date(2026, 7, 30) + timedelta(days=30),
        buyer_company="Cedar Ridge Outfitters",
        buyer_contact="Sarah Cole",
        buyer_email="sarah@cedarridge.com",
        buyer_address="118 Main St, Boise, ID 83702, USA",
        ship_to=None,
        currency="USD",
        subtotal=Decimal("1850.00"),
        freight=None,
        total=Decimal("1850.00"),
        notes=None,
        items_json=[
            {
                "sku": "PSPE-001",
                "name": "Portable Camping Shower",
                "variant": "3 colors",
                "qty": 100,
                "unit_price": "18.50",
                "line_total": "1850.00",
            }
        ],
        terms_json={
            "legal_entity": "Guangzhou Longjie E-Commerce Co., Ltd.",
            "address_lines": ["Room 1101", "Guangzhou, China"],
            "contact_email": "business@barongsupply.com",
            "contact_phone": "WhatsApp +1 (314) 203-8646",
            "payment_terms": (
                "50% deposit to initiate production; 50% balance against "
                "export documents before dispatch. Secure wire transfer "
                "(T/T) only - we do not accept credit card or PayPal."
            ),
            "delivery_line": "delivered to your door with import duty included",
            "lead_time_note": "Lead time starts once payment has cleared.",
            "country_of_origin": "China",
            "banking": {
                "beneficiary": "TEST CO LTD",
                "bank_name": "Test Bank",
                "swift": "TESTCNSH",
                "account": "1234567890",
            },
        },
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _pdf_text(data: bytes) -> str:
    import re
    import zlib

    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        body = match.group(1)
        try:
            chunks.append(zlib.decompress(body).decode("latin-1"))
        except Exception:  # noqa: BLE001
            try:
                chunks.append(body.decode("latin-1"))
            except Exception:  # noqa: BLE001
                pass
    return " ".join(re.findall(r"\((?:\\.|[^\\)])*\)", " ".join(chunks)))


def test_pdf_carries_everything_the_buyer_needs_to_wire_money() -> None:
    """买家拿这张纸去银行。**少一样他就汇不出来**,只能回来问——那一来一回
    可能就是几天,而报价只有 30 天有效期。
    """
    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    text = _pdf_text(render_pdf(_doc()))
    for needed in (
        "PROFORMA INVOICE",
        "PI-20260730-001",       # 单号:汇款附言要写
        "Cedar Ridge",           # 买方
        "PSPE-001",              # 买什么
        "1,850.00",              # 多少钱
        "TESTCNSH",              # SWIFT
        "1234567890",            # 账号
        "TEST CO LTD",           # 收款人
        "50% deposit",           # 付款条件
        "Valid until",           # 有效期
        "China",                 # 原产国
    ):
        assert needed in text, f"PDF 上缺: {needed}"


def test_pdf_states_the_payment_reference() -> None:
    """不写"汇款请注明单号",钱到账了对不上是哪一单——小客户尤其常见。"""
    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    text = _pdf_text(render_pdf(_doc()))
    assert "payment reference" in text
    assert "PI-20260730-001" in text


def test_pdf_keeps_the_card_refusal_visible() -> None:
    """死规矩:绝不接受信用卡/PayPal。单据上不写清楚,买家会拿卡来付,
    拒付了货款两空。"""
    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    assert "credit card" in _pdf_text(render_pdf(_doc()))


def test_document_never_renders_without_freight_promise_confusion() -> None:
    """运费留空时必须明说"另报",不能什么都不写——买家会以为总价就是到手价。"""
    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    text = _pdf_text(render_pdf(_doc(freight=None)))
    assert "Freight quoted separately" in text
    priced = _pdf_text(render_pdf(_doc(freight=Decimal("120.00"))))
    assert "120.00" in priced


def test_banking_requires_the_four_fields_that_move_money() -> None:
    """收款人/银行/SWIFT/账号缺一样,买家就汇不出去。"""
    from backend.app.modules.b2b.documents import banking

    assert banking.missing_required({}) == [
        label for _key, label, required in banking.FIELDS if required
    ]
    full = {
        "beneficiary": "A",
        "bank_name": "B",
        "swift": "C",
        "account": "D",
    }
    assert banking.missing_required(full) == []
    # 空白字符不算填了
    assert banking.missing_required({**full, "swift": "   "})


def test_terms_snapshot_is_taken_not_referenced() -> None:
    """**发出去的单据不能随源数据变。** 批发价过两天调了、条款改了,买家手上
    那张必须还是当时那个样子,否则拿旧单来付款双方对不上账。
    """
    from pathlib import Path

    import backend.app.modules.b2b.documents.service as svc

    source = Path(svc.__file__).read_text(encoding="utf-8")
    body = source[source.index("def create_proforma(") :]
    assert "terms_json={" in body
    assert "policies.PAYMENT_TERMS" in body
    assert '"banking": dict(profile)' in body


def test_tier_price_is_applied_automatically() -> None:
    """数量够了自动用更低那档。**买家不该靠自己发现优惠**,而手动挑档位
    迟早挑错——印错价的单子是要认的。"""
    from backend.app.modules.b2b.documents.service import _line

    item = SimpleNamespace(
        sku="ET-001",
        product_name="Squishy",
        variant_note=None,
        case_pack=24,
        wholesale_price=Decimal("2.40"),
        price_tiers_json=[
            {"min_qty": 100, "unit_price": "2.20"},
            {"min_qty": 500, "unit_price": "2.00"},
        ],
    )
    assert _line(item, 50)["unit_price"] == "2.40"
    assert _line(item, 100)["unit_price"] == "2.20"
    assert _line(item, 900)["unit_price"] == "2.00"
    assert _line(item, 900)["line_total"] == "1800.00"


# --------------------------------------------------------------------------
# 样品抵扣:我们已经承诺过四次的那句话
# --------------------------------------------------------------------------


def test_sample_credit_matches_by_full_email_never_by_domain() -> None:
    """和退订名单同一条死规矩:小店老板多用 gmail/outlook,按域名认会把
    张三的样品费抵给李四。"""
    from backend.app.modules.b2b.outreach.suppression import normalise

    assert normalise("Bob@gmail.com") != normalise("sarah@gmail.com")
    # +tag 是同一个人,该认出来
    assert normalise("bob+sample@gmail.com") == normalise("bob@gmail.com")


def test_credit_never_exceeds_the_goods_value() -> None:
    """抵成负数就变成我们倒欠钱,那张单没法看。"""
    from pathlib import Path

    import backend.app.modules.b2b.documents.sample_credits as credits

    source = Path(credits.__file__).read_text(encoding="utf-8")
    body = source[source.index("def consume(") :]
    assert "remaining" in body
    assert "if remaining <= 0" in body
    # 抵不完的留着，不是作废——承诺是"全额抵扣"不是"用一次作废"
    assert "continue" in body


def test_credit_is_applied_to_goods_not_freight() -> None:
    """运费是货代实付,抵掉等于我们贴钱。"""
    from pathlib import Path

    import backend.app.modules.b2b.documents.service as svc

    body = Path(svc.__file__).read_text(encoding="utf-8")
    body = body[body.index("def create_proforma(") : body.index("def create_shipping_document(")]
    assert "cap=document.subtotal" in body, "抵扣封顶必须是货款不是总额"


def test_credit_is_printed_on_the_invoice() -> None:
    """抵扣要印在单子上,不能只在后台扣掉——买家看到"你说过的样品费真的退给
    我了",比任何客套话都管用。"""
    from decimal import Decimal

    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    text = _pdf_text(
        render_pdf(_doc(sample_credit=Decimal("35.99"), doc_type="proforma_invoice"))
    )
    assert "sample credit" in text
    assert "35.99" in text


# --------------------------------------------------------------------------
# 发货那两张
# --------------------------------------------------------------------------


def test_commercial_invoice_and_packing_list_render() -> None:
    """批发页上已经承诺 every order 提供这两张。"""
    from backend.app.modules.b2b.documents.render_pdf import render_pdf

    ci = _pdf_text(render_pdf(_doc(doc_type="commercial_invoice", number="CI-1")))
    assert "COMMERCIAL INVOICE" in ci
    # 商业发票不是要约，印"有效期"会让报关的人困惑
    assert "Valid until" not in ci

    pl = _pdf_text(
        render_pdf(
            _doc(
                doc_type="packing_list",
                number="PL-1",
                carton_count=5,
                gross_weight_kg=Decimal("62.50"),
                net_weight_kg=None,
            )
        )
    )
    assert "PACKING LIST" in pl
    assert "Total cartons" in pl
    assert "62.50" in pl
    # 没填的重量印 TBC，不假装算得出来
    assert "TBC" in pl
    # 装箱单不谈钱，也不该印收款信息
    assert "SWIFT" not in pl


def test_packing_list_carton_count_rounds_up() -> None:
    """105 个 / 箱规 20 = 6 箱，不是 5.25 箱。"""
    from types import SimpleNamespace

    from backend.app.modules.b2b.documents.service import _line

    item = SimpleNamespace(
        sku="X", product_name="X", variant_note=None,
        wholesale_price=Decimal("1.00"), case_pack=20, price_tiers_json=None,
    )
    assert _line(item, 100)["cartons"] == 5
    assert _line(item, 105)["cartons"] == 6
    assert _line(item, 7)["cartons"] == 1


def test_shipping_documents_inherit_lines_from_the_proforma() -> None:
    """**报关金额必须和买家实付一致。** 重新从批发目录取,中途调过价就对不上
    ——那是海关最不能容忍的一种不一致。"""
    from pathlib import Path

    import backend.app.modules.b2b.documents.service as svc

    body = Path(svc.__file__).read_text(encoding="utf-8")
    body = body[body.index("def create_shipping_document(") :]
    assert "items_json=list(source.items_json or [])" in body
    assert "B2BWholesaleItem" not in body, "派生时不该再查批发目录"


# --------------------------------------------------------------------------
# 产品链接校验(补上和指南之间的不对称)
# --------------------------------------------------------------------------


def test_dead_products_are_dropped_from_wholesale_pages() -> None:
    from backend.app.modules.b2b.website import products_live

    groups = [
        {
            "thumbs": [{"url": "https://x/?p=1"}, {"url": "https://x/?p=2"}],
            "categories": [
                {
                    "products": [
                        {"url": "https://x/?p=1"},
                        {"url": "https://x/?p=2"},
                    ]
                },
                {"products": [{"url": "https://x/?p=2"}]},
            ],
        }
    ]
    removed = products_live.drop_dead_products(groups, {1})
    assert removed == 2
    assert groups[0]["count"] == 1
    # 整个类目的货都没了就把这一段也去掉，不留空标题
    assert len(groups[0]["categories"]) == 1
    assert groups[0]["thumbs"] == [{"url": "https://x/?p=1"}]


def test_unverifiable_products_are_kept_not_wiped() -> None:
    """核不了就一个都不删。把"查不到"当成"不存在",WP 抖一下就能清空整个批发页。"""
    from backend.app.modules.b2b.website import products_live

    groups = [
        {
            "thumbs": [],
            "categories": [{"products": [{"url": "https://x/?p=1"}]}],
            "count": 1,
        }
    ]
    assert products_live.drop_dead_products(groups, None) == 0
    assert groups[0]["categories"][0]["products"]
