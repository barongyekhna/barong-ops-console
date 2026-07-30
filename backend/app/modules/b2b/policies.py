"""B2B 对外口径的**唯一真相源**。

图册 PDF、产品页小窗、开发信模板——只要是给买家看的政策文字,全部从这里
渲染。**绝不允许任何一处再抄一份。**

2026-07-29 用户提出产品页小窗时定的规矩:政策原本写死在图册渲染器里,小窗
再抄一份就变成两处各存一份;哪天门槛从 $500 改成 $800,图册改了网页没改,
两边对不上——那又是一个 GMC 口径不一致的雷(他已经因为 Misrepresentation
被封过两次,只剩一次申诉机会)。

同一天用户刚纠正过我一次同类错误(把产品写死进 AI 提示词),这条是它的
推论:**能从一处派生的,绝不复制第二份。** 见 feedback-derive-dont-ask。
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

# --------------------------------------------------------------------------
# 身份(和 /contact/ 页一字不差,口径不一致正是 GMC 封号的理由)
# --------------------------------------------------------------------------
LEGAL_ENTITY = "Guangzhou Longjie E-Commerce Co., Ltd."
ADDRESS_LINES: tuple[str, ...] = (
    "Room 1101, Self-numbered B13",
    "No. 8 Jinsui Road, Tianhe District",
    "Guangzhou, Guangdong 510630, China",
)

# 零售售后邮箱,图册抬头用。
RETAIL_CONTACT_EMAIL = "service@barongyekhna.com"
# B2B 询盘专用信箱。和 service@(售后)、info@(法务)刻意分开,以后所有
# 批发/贴牌线索走同一个口子,好统计也好隔离。
B2B_CONTACT_EMAIL = "business@barongsupply.com"
# 图册会被买手转发、打印、四处流传,不放私人手机号;+86 对美加墨买家又贵
# 又不方便,只留 WhatsApp。网站联系页仍保留座机——那是 GMC 身份合规要求。
CONTACT_WHATSAPP = "+1 (314) 203-8646"
CONTACT_PHONE = f"WhatsApp {CONTACT_WHATSAPP}"

DEFAULT_CURRENCY = "USD"
DEFAULT_MIN_ORDER_VALUE = Decimal("300.00")

# --------------------------------------------------------------------------
# 政策数值。改这里,图册和产品页小窗同时生效。
# --------------------------------------------------------------------------
# 首单免运费门槛。**仅限海运**——UPS/DHL 红单一票就能吃掉整单利润。
FREE_SHIPPING_THRESHOLD = Decimal("500.00")
# 阶梯议价起点:起订量的几倍以上可以谈。
VOLUME_DISCOUNT_MULTIPLE = 5
# 报价有效期(天)。只对图册有意义,小窗上不显示价格所以不提。
QUOTE_VALID_DAYS = 30

# 定金比例。50/50 是外贸行规,买手一看就懂;整单预付会吓退新客户。
DEPOSIT_PERCENT = 50

# ⚠️ 死规矩(2026-07-27 用户拍板):**绝不接受信用卡/PayPal**。国际 B2B +
# 中国供应商,买家收货后发起拒付几乎申诉不赢,货款两空还倒贴手续费。
#
# 2026-07-29 口径统一:/wholesale/ 页面上写的是 50/50 分期,图册这边原来写
# "发货前一次付清"——**两处说法不一正是 GMC 判虚假陈述的那个病**。用户拍板
# 以页面的 50/50 为准(更像行规、买手更容易接受),图册跟着改。
PAYMENT_TERMS = (
    f"{DEPOSIT_PERCENT}% deposit to initiate production; "
    f"{100 - DEPOSIT_PERCENT}% balance against export documents before "
    f"dispatch. Secure wire transfer (T/T) only - we do not accept credit "
    f"card or PayPal."
)


def _free_shipping_sentence() -> str:
    """⚠️ "SEA FREIGHT ONLY" 这几个字**一个都不能删**。

    用户原话:"如果客户要走UPS红单我也给免运费那我要倾家荡产了"。
    有测试钉着这句话必须出现。
    """
    return (
        f"First order: free shipping on first wholesale orders of "
        f"{DEFAULT_CURRENCY} {FREE_SHIPPING_THRESHOLD:.0f} or more "
        f"- SEA FREIGHT ONLY. Express air (UPS / DHL / FedEx) is quoted "
        f"separately and paid by the buyer."
    )


def _sample_sentence() -> str:
    """样品**收费**、首单全额抵扣。用户纠正过一次口径,别写成免费。"""
    return (
        "Samples: sample units are credited in full against your first "
        "wholesale order, so samples cost you nothing once you order. "
        "Buyer covers sample shipping."
    )


def line_sheet_notes() -> tuple[str, ...]:
    """图册最后一页的完整政策。给已经在看价格的人,写全。"""
    return (
        f"Prices shown are our minimum-order (MOQ) prices. Larger orders are "
        f"negotiable: for quantities from {VOLUME_DISCOUNT_MULTIPLE}x the "
        f"listed MOQ, contact us for a volume quotation.",
        "Wholesale prices are exclusive of shipping and import duties.",
        "Lead time starts once payment has cleared.",
        f"Prices valid for {QUOTE_VALID_DAYS} days from the edition date "
        f"shown above.",
        _sample_sentence(),
        _free_shipping_sentence(),
    )


class WidgetPolicy(TypedDict):
    """产品页小窗上的一条卖点。短句,给还没决定要不要联系你的人看。"""

    key: str
    text: str


def widget_policies() -> tuple[WidgetPolicy, ...]:
    """产品页小窗显示的政策。**只挑降低对方风险的那几条。**

    刻意**不放**的三样(2026-07-29 与用户敲定):
    - 价格:GMC 会把"页面价与 feed 价不符"判成 Misrepresentation,他只剩
      一次申诉机会;而且藏起价格,小窗就从价目表变成留资器。
    - 只收电汇:负面表述,放钩子里劝退人,留到第一封回复再说。**但绝不
      能反过来暗示可以刷卡。**
    - 报价 30 天有效:这里根本没价格,写了没意义。

    ⚠️ 免运费那条**必须带 "Wholesale" 这个词**——和零售的"满 $100 免运费"
    明确区分,否则又是一个 GMC 口径打架的点。
    """
    return (
        {
            "key": "sample_credited",
            "text": (
                "Samples credited in full against your first order"
            ),
        },
        {
            "key": "free_shipping",
            "text": (
                f"Wholesale orders over {DEFAULT_CURRENCY} "
                f"{FREE_SHIPPING_THRESHOLD:.0f} ship free "
                f"- sea freight only"
            ),
        },
        {
            # 别写 "OEM/ODM":每封中国工厂群发的垃圾邮件都是这四个字母,
            # 美国零售商看到就归类成阿里巴巴供应商。他们自己叫 private label。
            "key": "private_label",
            "text": "Private label available on larger runs",
        },
    )


# 小窗上不写起订门槛数字:写了吓跑真买家,不写只会招来"50 个能定制吗"
# ——后者好处理,前者损失不可逆。数量在回复里问(reply_oem 模板第一句)。
# 领头放 "Wholesale":店家扫页面/Ctrl+F 找的就是这个词,"Buying for a store"
# 意思对但不是他在搜的那个词(2026-07-29 用户提)。
WIDGET_HEADLINE = "Wholesale - buying for a store?"
WIDGET_SUBLINE = "Wholesale available - direct from our own factory"
WIDGET_CTA = "Request wholesale pricing"


# --------------------------------------------------------------------------
# /wholesale/ 页面文案。**页面由控制台生成,这里是唯一出处。**
# --------------------------------------------------------------------------
# ⚠️ 这段是全站最容易踩虚假陈述的地方:品类跨度大,不解释清楚,采购的第一反应
# 不是"实力雄厚"而是"这是贸易公司吧"——在这行里专精的工厂比什么都做的可信。
#
# 刻意**不写**年限/员工数/产能/认证/客户案例:用户因 Misrepresentation 被封过
# 两次、**只剩一次申诉机会**,网站上任何一句查不实的话都是在那根线上跳舞。
# 下面每一句都可核实,且和 /contact/ 页的主体、地址一致。
WHOLESALE_INTRO_TITLE = "Why our range crosses categories"
WHOLESALE_INTRO_LEAD = (
    "We're an assembly and integration factory, not a single-product plant."
)
WHOLESALE_INHOUSE = ("assembly", "function testing", "packing", "outgoing QC")
WHOLESALE_PARTNERED = ("tooling", "batteries", "motors", "raw materials")
WHOLESALE_INTRO_CLOSE = (
    "That's how a product goes from concept to a finished, packed, "
    "export-ready SKU - and why our range crosses categories. The constant "
    "is the line that builds and checks it, not the product type."
)
WHOLESALE_INTRO_PROOF = (
    "Everything ships from our own facility in Guangzhou. "
    "No trading company in between."
)

# 店型卡片上的鼓励语。用户拍板:**不写 MOQ 数字**(不同产品不一样,写区间显得乱),
# 但要有一句降低心理门槛的话。"one case" 比 "small MOQ" 具体得多。
LOW_MINIMUM_LINE = "Low minimums - most lines start at one case."


def who_we_work_with() -> tuple[tuple[str, str], ...]:
    """三类买家。第三类**绝不写 OEM/ODM**——每封中国工厂群发的垃圾邮件都是
    这四个字母,美国零售商看到就归类成阿里巴巴供应商。他们自己叫 private label。
    """
    return (
        (
            "Retailers",
            "Specialty and general retailers looking for well-documented, "
            "ready-to-sell products with complete spec sheets and imagery.",
        ),
        (
            "Distributors & e-commerce sellers",
            "Volume buyers who need dependable lead times, export "
            "documentation, and consistent batch quality.",
        ),
        (
            "Private label projects",
            "Custom configurations, packaging, or own-brand programs built "
            "on our manufacturing base - quoted case by case.",
        ),
    )


def how_it_works() -> tuple[tuple[str, str], ...]:
    return (
        (
            "Tell us what you need.",
            "Product lines, target quantities, and destination market.",
        ),
        (
            "Quote & samples.",
            "We reply with current pricing tiers, MOQs for the lines you "
            "selected, and sample options.",
        ),
        (
            "Production & delivery.",
            "Confirmed orders go into production with agreed lead times, "
            "full export documentation, and tracked freight.",
        ),
    )


def wholesale_terms() -> tuple[tuple[str, str], ...]:
    """页面上的「Terms at a glance」。**和图册同源** —— 数值改一处两处生效。

    这里比 line_sheet_notes() 短:图册是给已经在看价格的人,写全;页面是给还没
    决定要不要联系你的人,只挑降低他风险的几条。
    """
    return (
        (
            "Pricing & MOQ",
            "vary by product line and quantity; request the current line "
            "sheet for exact tiers.",
        ),
        ("Payment", PAYMENT_TERMS),
        (
            "Samples",
            "sample units are credited in full against your first wholesale "
            "order, so samples cost you nothing once you order. Buyer covers "
            "sample shipping.",
        ),
        (
            "First order",
            f"free shipping on first wholesale orders of {DEFAULT_CURRENCY} "
            f"{FREE_SHIPPING_THRESHOLD:.0f} or more - sea freight only. "
            f"Express air (UPS / DHL / FedEx) is quoted separately and paid "
            f"by the buyer.",
        ),
        (
            "Documentation",
            "commercial invoice, packing list, and shipping documents "
            "provided for every order.",
        ),
    )
