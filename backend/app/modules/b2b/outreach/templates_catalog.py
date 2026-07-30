"""内置开发信模板目录。**代码是真相源**,和店型目录同一套路。

2026-07-29 与用户敲定的模板体系:一共只有 7 类,**只有首封随店型变**——
所以以后店型涨到 24 个,也不是 24 套模板。

写作原则(都是用户实际业务约束推出来的,不是文风偏好):
- **首封绝不带附件**:带附件直接进垃圾箱。图册只在"要价格表"那封回复里发。
- **首封不装大**:小店老板信"small factory",不信 "leading manufacturer"。
- **样品收费、首单全额抵扣**(用户 2026-07-27 拍板改过一次口径,别写成免费)。
- **免运费仅限海运**:UPS/DHL 空运另计买家自付。写漏这四个字会赔到破产。
- **绝不出现信用卡/PayPal**:B2B 拒付风险,用户死命令只收电汇。有校验钉着。
- 跟进信**接在原邮件下回复**并主动给"不要"的出口,回复率显著更高。
"""

from __future__ import annotations

from typing import TypedDict

KIND_FIRST_TOUCH = "first_touch"
KIND_FOLLOW_UP = "follow_up"
KIND_REPLY_PRICING = "reply_pricing"
KIND_REPLY_MOQ = "reply_moq"
KIND_REPLY_SAMPLE = "reply_sample"
KIND_REPLY_OEM = "reply_oem"
KIND_REPLY_NO = "reply_no"

KIND_LABELS = {
    KIND_FIRST_TOUCH: "首封开发信",
    KIND_FOLLOW_UP: "跟进信（4-7 天后）",
    KIND_REPLY_PRICING: "回复：要价格表",
    KIND_REPLY_MOQ: "回复：问起订量/价格",
    KIND_REPLY_SAMPLE: "回复：要样品",
    KIND_REPLY_OEM: "回复：问贴牌 OEM",
    KIND_REPLY_NO: "回复：婉拒",
}

# 只有首封随店型变;其余 6 类全店型共用。
STORE_TYPE_SCOPED_KINDS = (KIND_FIRST_TOUCH,)

# 这些字眼一旦出现在模板里就是事故,存模板时硬校验。
FORBIDDEN_PHRASES = (
    "credit card",
    "paypal",
    "信用卡",
)


class TemplateSpec(TypedDict):
    kind: str
    language: str
    store_type: str | None
    subject: str
    body: str


# 可用占位符。渲染时缺哪个就留空,不报错——首封的 personal_line 由 AI 写。
PLACEHOLDERS = (
    "{store_name}",
    "{contact_name}",
    "{personal_line}",
    "{product_line}",
    "{city}",
    "{sender_name}",
    "{sender_domain}",
)


_FIRST_TOUCH_EN = """Hi {contact_name},

{personal_line}

I run a small factory in Guangzhou — we assemble, test and pack everything \
ourselves. Right now we make {product_line}.

Samples aren't free, but the full sample cost comes off your first wholesale \
order, so if you do order it ends up costing you nothing. Buyer covers sample \
shipping.

Want me to send you one?

{sender_name}
{sender_domain}"""

_FIRST_TOUCH_ES = """Hola {contact_name}:

{personal_line}

Tengo una fábrica pequeña en Guangzhou — nosotros mismos armamos, probamos y \
empacamos todo. Actualmente fabricamos {product_line}.

Las muestras no son gratis, pero el costo completo de la muestra se descuenta \
de su primer pedido mayorista, así que si compra, la muestra le sale gratis. \
El envío de la muestra corre por cuenta del comprador.

¿Le mando una?

{sender_name}
{sender_domain}"""

_FOLLOW_UP_EN = """Hi {contact_name},

Following up on this — I know the inbox gets busy.

If this isn't a fit for your shelves, just reply "no thanks" and I'll stop \
bothering you. If you're curious, I can drop a sample in the mail this week.

{sender_name}"""

_FOLLOW_UP_ES = """Hola {contact_name}:

Le doy seguimiento a mi mensaje anterior — sé que la bandeja se llena.

Si no encaja con lo que vende, responda "no, gracias" y no lo molesto más. \
Si le da curiosidad, puedo enviarle una muestra esta semana.

{sender_name}"""


def _catalog() -> tuple[TemplateSpec, ...]:
    specs: list[TemplateSpec] = []

    # 首封:按店型 × 语言。store_type=None 的那条是兜底,新店型没写专属文案
    # 时用它,保证永远有得发。
    for language, subject, body in (
        ("en", "samples for {store_name}?", _FIRST_TOUCH_EN),
        ("es", "¿muestras para {store_name}?", _FIRST_TOUCH_ES),
    ):
        specs.append(
            {
                "kind": KIND_FIRST_TOUCH,
                "language": language,
                "store_type": None,
                "subject": subject,
                "body": body,
            }
        )

    for language, subject, body in (
        ("en", "re: samples for {store_name}?", _FOLLOW_UP_EN),
        ("es", "re: ¿muestras para {store_name}?", _FOLLOW_UP_ES),
    ):
        specs.append(
            {
                "kind": KIND_FOLLOW_UP,
                "language": language,
                "store_type": None,
                "subject": subject,
                "body": body,
            }
        )

    replies_en: tuple[tuple[str, str, str], ...] = (
        (
            KIND_REPLY_PRICING,
            "line sheet - {store_name}",
            """Hi {contact_name},

Attached is our current line sheet.

Prices shown are at MOQ. If you're ordering 5x MOQ or more, tell me the \
quantity and I'll quote you better.

Two things worth knowing up front: samples are charged but credited in full \
against your first order, and first orders over USD 500 ship free by sea \
freight only — air couriers (UPS / DHL / FedEx) are quoted separately and \
paid by the buyer.

{sender_name}""",
        ),
        (
            KIND_REPLY_MOQ,
            "re: MOQ and pricing",
            """Hi {contact_name},

MOQ and case pack are listed per style on our line sheet, and the unit price \
comes down at 5x MOQ.

Want me to send the full line sheet so you can see the whole range?

{sender_name}""",
        ),
        (
            KIND_REPLY_SAMPLE,
            "re: sample",
            """Hi {contact_name},

Happy to. The sample is charged, but I credit the full sample cost against \
your first wholesale order — so if you order, the sample ends up free. \
Shipping on the sample is on you.

What's the best address to send it to?

{sender_name}""",
        ),
        (
            KIND_REPLY_OEM,
            "re: private label",
            """Hi {contact_name},

We do private label. Before I quote, two questions:

1. Roughly what quantity are you thinking?
2. Do you want your logo on the product itself, or just on the packaging?

Packaging-only is much cheaper and much faster — most first private label \
orders start there.

{sender_name}""",
        ),
        (
            KIND_REPLY_NO,
            "re: thanks",
            """Hi {contact_name},

No problem at all, and thanks for the quick reply.

If it ever changes, I'm here. Good luck with the season.

{sender_name}""",
        ),
    )
    for kind, subject, body in replies_en:
        specs.append(
            {
                "kind": kind,
                "language": "en",
                "store_type": None,
                "subject": subject,
                "body": body,
            }
        )
    return tuple(specs)


TEMPLATE_CATALOG: tuple[TemplateSpec, ...] = _catalog()


def forbidden_phrase_in(text: str) -> str | None:
    """模板里出现支付方式红线词就拦下。用户死命令:B2B 只收电汇。"""
    lowered = (text or "").lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            return phrase
    return None
