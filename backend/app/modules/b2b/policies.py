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
# 首单免运费**封顶**(用户拍板 2026-07-30)。
#
# **为什么必须封顶**:门槛按订单金额,而运费成本按重量/体积——两者不挂钩。
# 按 ¥5/公斤算,$500 的花洒单运费约 $37(7%),但换成一个 $3、2kg 的品,
# 同样 $500 就是 334 公斤 ≈ $230(46%)——**这一单白干还倒贴**。
# 而且我们是**无固定品类工厂**,将来上什么品自己都还不知道,哪天上个又便宜
# 又重的东西,这条承诺当场变成陷阱。海运大货还按体积计费,蓬松货更狠。
#
# 用金额封顶而不是限重:限重要按产品逐个调,**金额封顶跟品类无关**。
FREE_SHIPPING_CAP = Decimal("150.00")
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


# 到门 + 含税。**这是我们最强的一条,不是细节**(2026-07-30 用户交底):
# 货代把关税包进运费里,所以报给买家的运费就是全部——他不用算税、不用找报关行、
# 不会在收货时被追加账单。美国小零售店最怕的正是"货到港了突然收到海关账单"。
# 私人/店铺地址一样能清关,只比发 FBA 仓贵 ¥1/公斤左右。
#
# ⚠️ 措辞刻意**不用 Incoterm 术语**(DDP/FOB/EXW):买手看得懂大白话,而术语一旦
# 用错就是合同层面的口径错误。说清楚"谁付什么"比说对术语重要。
DELIVERY_LINE = (
    "delivered to your door with import duty included - no customs broker "
    "and no surprise bill on arrival"
)


# 瑕疵免费换、不用寄回(2026-07-30 用户拍板)。
#
# **为什么"不用寄回"不是让利,是算出来的**:美→中最便宜 $2/磅,中→美海运
# ¥4-5/公斤(≈$0.25-0.31/磅),差约 8 倍。让客户把一个瑕疵品寄回来,运费比货本身
# 还贵。直接补发既省钱、客户体验还更好——这是双赢,不是我们吃亏。
#
# **补发跟下一单走**:单独空运一件补货,运费能超过货值。跟下一单一起发是行规;
# 客户不想等就折价退款,给他选。
#
# ⚠️ 死规矩:**只讲瑕疵,绝不写成"X 天内可退"那种结构化退货窗口**。真实政策
# 就是只保缺陷、不接受"不想要了",而结构化退货窗口正是 GMC 判 Misrepresentation
# 的写法(只剩一次申诉机会)。有测试钉着不许出现天数窗口。
DEFECT_POLICY = (
    "Inspect your shipment on arrival. If anything is damaged or defective, "
    "send us photos - we replace it free with your next order, or credit it "
    "if you would rather not wait. You never ship anything back to China."
)


def _free_shipping_sentence() -> str:
    """⚠️ "SEA FREIGHT ONLY" 这几个字**一个都不能删**。

    用户原话:"如果客户要走UPS红单我也给免运费那我要倾家荡产了"。
    海运 ¥4-5/公斤 vs 空运快递贵一个数量级,免错了就是倾家荡产。
    有测试钉着这句话必须出现。
    """
    return (
        f"First order: free shipping on first wholesale orders of "
        f"{DEFAULT_CURRENCY} {FREE_SHIPPING_THRESHOLD:.0f} or more "
        f"- SEA FREIGHT ONLY, delivered to your door, up to "
        f"{DEFAULT_CURRENCY} {FREE_SHIPPING_CAP:.0f} of freight; anything "
        f"above that is billed at cost. Express air (UPS / DHL / FedEx) is "
        f"quoted separately and paid by the buyer."
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
        # 旧版只写 "exclusive of shipping and import duties" —— 技术上没错,
        # 但等于把算税这件事甩回给买家,而买家算不出来就不回你了。实际是货代
        # 包税到门,所以把话说全:价里不含运费,但运费报出来就是到门的全部。
        f"Wholesale prices do not include freight. Freight is quoted "
        f"separately and {DELIVERY_LINE}.",
        "Lead time starts once payment has cleared.",
        DEFECT_POLICY,
        # 图册是完整政策文档,把「只保缺陷」说明白;页面上不写这句(销售页上
        # 的负面表述劝退人),但两处**不矛盾**——页面只是没提,不是承诺了别的。
        "Wholesale orders are not returnable for change of mind.",
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
            # ⚠️ "First" 一个字都不能少(2026-07-30 用户抓到我漏了):免运费**只有
            # 首单**。漏掉 first 就读成"每一单都免运费"——既是白送钱,也是页面/
            # 图册说 first、小窗说每单的口径打架,而口径打架正是 GMC 判虚假陈述
            # 的那个病。有测试钉着。
            "key": "free_shipping",
            "text": (
                f"First wholesale order over {DEFAULT_CURRENCY} "
                f"{FREE_SHIPPING_THRESHOLD:.0f} ships free "
                f"- sea freight only, up to {DEFAULT_CURRENCY} "
                f"{FREE_SHIPPING_CAP:.0f}"
            ),
        },
        {
            # 小窗上最能止住"从中国进货好麻烦"这个念头的一条。短句,不展开——
            # 展开是 /wholesale/ 页面的活。
            "key": "duty_included",
            "text": "Delivered to your door, import duty included",
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
# 刻意**不写**年限/员工数/产能/客户案例:用户因 Misrepresentation 被封过两次、
# **只剩一次申诉机会**,网站上任何一句查不实的话都是在那根线上跳舞。
# 下面每一句都可核实,且和 /contact/ 页的主体、地址一致。
#
# ── 关于「年限」,2026-09-02 用户拍板**删掉,并写回这份禁写清单**。
# 2026-08-01 那版曾把「年限」从清单里划掉、正文写了首次出货年份。
# 年份本身是真的,不构成任何问题 —— 删它跟真假无关,是因为**开厂时间
# 对买手的采购决策不产生任何影响**,它唯一的作用是给对方一个可以拿去
# 掂量你"够不够老"的把柄。这一页要立的是"我们跑过四省三十多家电机厂"
# 这种别人抄不走的具体事实,不是资历。少一个可被拿来称重的数字,
# 就少一处不必要的暴露面。
# **以后要往公开页面加任何时间/年限,先回来看这段。**
#
# ── 2026-08-01 重写。原版全是**类别词**("我们做装配""我们外协电机"),
# 任何一家贸易公司都能一字不改抄走,买手看了不会更信,只会归档成"标准话术"。
# 可信只来自两件事,这一版两件都上:
#   ① 一个别人抄不走的具体例子 —— 用户亲自跑供应商的数字(见下)和潜水泵密封;
#   ② 主动说出自己不做什么 —— 敢划边界的供应商才像真做实业的。
WHOLESALE_INTRO_TITLE = "Why our range crosses categories"
WHOLESALE_INTRO_LEAD = (
    "We're a product engineering and assembly plant - our own design, "
    "our own line, our own process technology."
)
WHOLESALE_INHOUSE = (
    "product design",
    "process development",
    "assembly",
    "100% function testing",
    "retail packing",
    "outgoing QC",
)
WHOLESALE_PARTNERED = (
    "motors",
    "battery cells",
    "PCBA",
    "injection tooling",
    "raw materials",
)
# ⚠️ 数字全部来自用户 2026-08-01 口述,**一个都不许改写、不许"约等于"**:
# 电机 4 省 30+ 家、电池 不到 10 家、电路板 17 家、模具 3 省 12 家现固定 2 家。
# 这段是全页最值钱的一段——贸易公司编不出"背着包跑了三十多家电机厂"。
# ⚠️ **认证一个字都不许写上公开页面**(用户 2026-08-01 拍板,他吃过亏)。
# 骗认证是这行的常见套路:装成买家要走认证文件,拿到就拉黑,压根不下单。
# 而且比"认证被白拿"更严重的是——**认证文件上印着供应商的名字**,发出去
# 泄的是四省跑三十多家才敲定的供应链名单,那往往才是对方真正想要的东西。
#
# 门槛这层意思用 "We turned down almost all of them" 表达:同样说明有标准、
# 有取舍,但**不给对方一个可以伸手要文件的抓手**。谁要文件谁开口,给不给
# 是逐单人工决定,不是页面上的公开承诺。
WHOLESALE_INTRO_SOURCING = (
    "We picked every supplier on foot. Before the plant shipped its first "
    "unit, we visited more than thirty motor factories across four "
    "provinces, close to ten battery makers, seventeen PCBA shops, and "
    "twelve tooling shops across three provinces. We turned down almost "
    "all of them. The ones we kept are the ones we still buy from today."
)
# ⚠️ "泡了一个月"刻意写成**我们自己做过的一次测试**,不是产品规格。
# 写成 "30-day submersion rated" 就等于给零售商一条可索赔的性能承诺,
# 而我们的退货口径只认瑕疵、不接受无理由退——承诺必须配机制,这条没机制。
#
# ── 2026-09-02 加固:这层保护原本**只活在这条 Python 注释里**,
# 看页面的人什么都读不到,照样可能把它当耐久指标去索赔。现在把
# "our own bench test on one unit, not a published rating" 写进正文,
# 让免责和事实出现在同一句话里。这正是「承诺必须配机制」的正解:
# 没有机制兜底的话,就在原地说清楚它不是承诺 —— 而不是指望没人误读。
# (措辞用 rating 不用 rated:测试禁的是 "rated" 那种规格化说法。)
WHOLESALE_INTRO_CLOSE = (
    "Our camping shower is the clearest example of what that buys you. "
    "The battery, motor, and PCBA are all sealed inside the main housing, "
    "and the whole unit sits underwater the entire time it runs. We "
    "developed that sealing process ourselves because nothing off the "
    "shelf survived it - we left one running in a tank for a month and it "
    "still worked. That was our own bench test on one unit, not a "
    "published rating. Immersion heaters come off the same line for the same "
    "reason: the hard part is sealing and testing, and that's the part we "
    "own."
)
# 边界段。**反直觉但真实**:采购最信的是敢说"这个我们不做"的供应商。
# 顺带把责任落到发票和保修上——那才是零售商真正在担的风险。
WHOLESALE_INTRO_LIMITS = (
    "What we don't do: we don't wind motors or make battery cells. We "
    "qualify those suppliers and we take responsibility for the finished "
    "unit - which is what your invoice and your customer's warranty "
    "actually depend on."
)
# ⚠️ 2026-07-31 更正:这里原来写 "our own facility in Guangzhou",**是错的**。
# 广州龙杰是**销售主体**(开票、收款、GMC 账户、独立站注册主体),注册地是天河区
# 一间写字楼;**生产全部在吉林那家电子产品制造公司**(用户是法人)。
#
# 原句还有一处更险的:"No trading company in between"——用户名下确实还有一家
# 深圳贸易公司。那家既不卖货也不生产,**网站上一个字都不该提**(当初封号的
# 真根因就是"同域名下两家公司打架")。
#
# **规则:谁卖货、谁收钱、谁生产,三件事各自说清楚,全站口径一致。** 多主体
# 完全合法,封号封的是自相矛盾。收款(PayPal C 端 / WorldFirst B 端)都在龙杰,
# 所以卖方口径本来就是一致的,只需要把"生产在哪"改对。
WHOLESALE_INTRO_PROOF = (
    "The factory is ours - products are made at our own plant in "
    "Jilin, China."
)
# 卖方单独一句。买家账单上看到的就是这个名字,和网站必须一字不差。
WHOLESALE_SELLER_LINE = (
    "Sold and invoiced by Guangzhou Longjie E-Commerce Co., Ltd."
)

# 工厂实拍(2026-07-31 用户提供,吉林自有工厂)。**四张各答一个买手的疑问**:
#   装配 → 真人真在做我们自己的产品     测试 → 每台都测,不是嘴上说
#   包装 → 有零售彩盒,能直接上货架       跨品类 → 加热棒,证明不止一个品
# 最后一张最值钱:"品类这么杂是不是贸易公司"才是买手真正在犯嘀咕的那句,
# 而它正是页面这一段的标题。图和字互相印证。
#
# ⚠️ 曾经想用 AI 生成的"气派"厂房图,已弃用:配在"our own facility"旁边就是
# 虚假陈述(GMC 只剩一次申诉机会),而且 B2B 买手一旦认出是 AI 图,结论不是
# "这人用了 AI",是"这人不是真工厂"——比没有照片伤得多。
FACTORY_PHOTOS: tuple[dict[str, str], ...] = (
    {
        "url": "https://barongyekhna.com/wp-content/uploads/2026/07/factory-assembly-tight.webp",
        "alt": (
            "A worker driving screws into a camping shower pump housing, "
            "with rows of assembled housings on the bench at the Barong "
            "Yekhna plant in Jilin, China"
        ),
        "caption": (
            "Our own line in Jilin, assembling the pump housings that go "
            "into every Barong Yekhna camping shower."
        ),
    },
    {
        "url": "https://barongyekhna.com/wp-content/uploads/2026/07/factory-testing.webp",
        "alt": (
            "Multimeter on the workbench next to a DC pump motor and a "
            "lithium battery pack with its protection board"
        ),
        "caption": (
            "Every motor and battery pack is checked on the bench before "
            "it goes into a shower."
        ),
    },
    {
        "url": "https://barongyekhna.com/wp-content/uploads/2026/07/factory-packing.webp",
        "alt": (
            "Stacks of printed retail boxes for the Panda portable camping "
            "shower, packed and ready to ship"
        ),
        "caption": (
            "Finished goods in our own retail packaging - ready for your "
            "shelf, not just a plain carton."
        ),
    },
    {
        "url": "https://barongyekhna.com/wp-content/uploads/2026/07/factory-range-1.webp",
        "alt": (
            "Rows of assembled immersion heater elements with cords and "
            "plugs on a rack at the Barong Yekhna plant"
        ),
        "caption": (
            "Not just showers - immersion heaters on the same line. The "
            "constant is the team that builds and checks it, not the "
            "product type."
        ),
    },
)

# ⚠️ 这里曾经写着 "Low minimums - most lines start at one case."
# **2026-07-30 用户拍板删掉**:起订量和箱规是两个独立填的数,没有任何机制保证
# "一箱起订"是真的。哪天某个产品填了箱规 20、起订量 200,页面还在说一箱起订,
# 买家按一箱来问,我们说不行——那是我们自己写的字打自己的脸。
#
# **兑现不了的承诺就删掉那句话**,而不是加一个校验去将就它(见记忆
# promise-needs-mechanism)。起订量本来就逐款不同,写在图册上按款列最准确。
MOQ_LINE = "MOQ and case pack are listed per style on our line sheet."


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
            # 单独一条,不跟"首单免运费"挤在一起——这是买家决定要不要回你的
            # 那个点,挤在括号里会被扫过去。
            "Freight & duty",
            f"freight is quoted separately and {DELIVERY_LINE}.",
        ),
        (
            "First order",
            f"free shipping on first wholesale orders of {DEFAULT_CURRENCY} "
            f"{FREE_SHIPPING_THRESHOLD:.0f} or more - sea freight only, up to "
            f"{DEFAULT_CURRENCY} {FREE_SHIPPING_CAP:.0f} of freight; anything "
            f"above that is billed at cost. Express air (UPS / DHL / FedEx) "
            f"is quoted separately and paid by the buyer.",
        ),
        (
            "Defects",
            DEFECT_POLICY[0].lower() + DEFECT_POLICY[1:],
        ),
        (
            "Documentation",
            "commercial invoice, packing list, and shipping documents "
            "provided for every order.",
        ),
    )
