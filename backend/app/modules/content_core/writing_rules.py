"""跨内容系列共享的**反垃圾家规**——一字一句都是踩出来的。

为什么抽出来:GEO 和 SEO 写的东西完全不同(买家问句 vs 工艺故事),但"什么算
垃圾"是同一套判断。如果两边各抄一份,迟早会漂:一边改了「不值得那段不许推销
收尾」,另一边还留着旧版,而**没有任何测试会发现**——两边都还是合法的提示词。

所以这里只放**与写哪种内容无关**的规则。选题依据、体裁结构、发布目的地永远
各自持有(``geo_series`` / ``seo_series`` 各自的 prompt_skills)。

每一条都对应一次真实事故:
- ARITHMETIC —— 护栏曾经惩罚精确:写 2.4 被判编造,含糊成 2 反而放行。
- ANSWER THE QUESTION —— 首批 GEO 内容"罗列参数不是回答"。
- JUDGEMENT —— 只说好话的页面既不可信也不会被 AI 引用;「别买」那段拐回推销
  就等于自毁。
- NO FABRICATION —— 最高铁律,重写链尤其容易破防(批评要求补数据时)。
"""

from __future__ import annotations

# --- 英文侧(生成链用) -------------------------------------------------------

ARITHMETIC_EN = (
    "ARITHMETIC IS ALLOWED — BUT SHOW YOUR WORK. You may compute a number the "
    "facts imply (\"5 gallons at 2.11 GPM lasts about 2.4 minutes\"), and you "
    "SHOULD when the question asks for one — but every computed number MUST be "
    "declared in `derived_numbers` as {\"value\": \"2.4\", \"from\": "
    "\"5 / 2.11\", \"unit\": \"minutes\"}. Each operand must come from the "
    "product facts or from the question itself; the server re-runs the "
    "arithmetic and rejects the piece if it does not check out. Do NOT round a "
    "number into vagueness to avoid declaring it — precision is the point.\n"
)

ANSWER_THE_QUESTION_EN = (
    "ANSWER THE QUESTION — DO NOT DESCRIBE THE PRODUCT. A question is answered "
    "when a reader who has NOT made up their mind can now make it up. Reciting "
    "the product's specifications is NOT an answer to a judgement question; it "
    "is a product description wearing a question as a hat. Specs are evidence "
    "FOR a judgement, never a substitute for one. If you find yourself listing "
    "what the product has, stop and write what that means for the reader's "
    "decision instead.\n"
)

JUDGEMENT_STRUCTURE_EN = (
    "JUDGEMENT QUESTIONS (\"is it worth it\", \"should I\", \"do I need\", "
    "\"is it any good\") MUST be structured as a decision, in this order:\n"
    "  1. a direct verdict in the first sentence, conditional and honest — "
    "\"Yes, if …\" / \"Not really, if …\";\n"
    "  2. the conditions under which it IS worth it, each tied to a mechanism "
    "or a verified fact (not a list of features);\n"
    "  3. **the conditions under which it is NOT worth it** — this half is "
    "mandatory. Naming who should not buy is what makes the page credible to a "
    "reader and citable by an answer engine; a page that only sells gets "
    "neither. Saying \"if your campsite already has a shower block, the value "
    "is low\" invents nothing — it is a conditional, not a claim of fact;\n"
    "  4. only then, where THIS product lands in that framework.\n"
    "The \"not worth it\" part must contain NO sales language and must NOT end "
    "by pivoting back to the product — a paragraph about who should not buy "
    "loses all of its credibility, and therefore all of its citation value, "
    "the moment it closes with a pitch. Keep the product's placement in step 4, "
    "where it belongs.\n"
    "This structure is a requirement, not a suggestion.\n"
)

# --- 中文侧(重写链用,与英文侧同义) ------------------------------------------

NO_FABRICATION_ZH = (
    "**最高铁律:绝不编造事实。**只能用给你的事实。如果某条批评要求补充一个"
    "事实里没有的数据(例如「应说明推荐充电功率」但规格里根本没有功率),"
    "**绝对不许瞎编一个数字或说法来满足它**——把这条批评放进 `unaddressed`,"
    "说明缺什么数据。宁可不改,也不许造假。\n"
)

ARITHMETIC_ZH = (
    "**算术是允许的,但必须亮算式。**可以算出事实蕴含的数字(如「5 加仑按 "
    "2.11 GPM 约 2.4 分钟」),问句要答案时**就该算**;但每个算出来的数字必须"
    "在 `derived_numbers` 里声明 {\"value\":\"2.4\",\"from\":\"5 / 2.11\"},"
    "每个操作数要么来自产品事实、要么来自问句本身。服务端会重算一遍,对不上"
    "就整篇打回。**不许为了躲开声明而把数字含糊掉**——精确才是价值所在。\n"
)

ANSWER_THE_QUESTION_ZH = (
    "**回答问句,不要介绍产品。**一个问题被回答的标准是:还没拿定主意的读者"
    "读完能拿定主意。罗列产品参数**不构成**对判断题的回答——那是「产品介绍"
    "戴了个问句的帽子」。参数是判断的**证据**,不是判断本身。如果原稿主要在"
    "堆参数,这次重写必须改成讲清楚**这些参数对读者的决定意味着什么**。\n"
)

JUDGEMENT_STRUCTURE_ZH = (
    "**判断类问句**(值不值/要不要买/好不好/该选哪个)必须写成决策结构:"
    "①第一句给条件式结论(Yes, if… / Not really, if…);②什么情况下值得,"
    "每条挂在机制或真实事实上;③**什么情况下不值得——这半边是强制的**;"
    "④最后才说本产品落在这个框架的哪里。说「如果营地本来就有淋浴房则价值"
    "不大」**没有编造任何东西**,它是条件判断不是事实主张,所以不受"
    "「绝不编造」约束。**「不值得」那一段里不许出现推销语言、不许拐回产品"
    "收尾**——一段专门讲别买的文字以推销结尾,就等于自毁可信度。\n"
)

NO_NAME_REPETITION_ZH = (
    "**别每句话都写产品全称**。第一次点名后改用简称或代词,句句全称读起来"
    "很生硬,也会挤掉真正有信息量的内容。\n"
)

__all__ = [
    "ANSWER_THE_QUESTION_EN",
    "ANSWER_THE_QUESTION_ZH",
    "ARITHMETIC_EN",
    "ARITHMETIC_ZH",
    "JUDGEMENT_STRUCTURE_EN",
    "JUDGEMENT_STRUCTURE_ZH",
    "NO_FABRICATION_ZH",
    "NO_NAME_REPETITION_ZH",
]
