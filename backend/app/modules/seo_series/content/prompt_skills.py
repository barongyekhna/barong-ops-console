"""SEO 内容的写作家规。

**反垃圾条款与 GEO 用的是同一批常量**(``content_core.writing_rules``),不是
抄一份——抄一份就会漂,而漂了没有任何测试能发现:两边都还是合法提示词。

不同的只有**形状**:
- GEO 追求"可被 AI 摘走的自足问答块"——碎、密、每块自成一体。
- SEO 追求"编辑体":一篇有主线的文章,中等长度,结构清晰。

**不为凑字数灌水。** 长文在 AI 搜索时代正在贬值:答案引擎摘的是自包含的段落,
不是三千字里第 2100 字那句。所以 SEO 也要求每个 H2 段落能独立成立——
只是它们串成一条论证线,而不是并列的问答。
"""

from __future__ import annotations

from ...content_core.writing_rules import (
    ANSWER_THE_QUESTION_EN,
    ANSWER_THE_QUESTION_ZH,
    ARITHMETIC_EN,
    ARITHMETIC_ZH,
    JUDGEMENT_STRUCTURE_EN,
    JUDGEMENT_STRUCTURE_ZH,
    NO_FABRICATION_ZH,
    NO_NAME_REPETITION_ZH,
)

SEO_CONTENT_SKILL_VERSION = "seo-content-v1"

# 每种体裁的骨架。给模型**结构**而不是字数——字数要求只会换来注水。
_KIND_BRIEF = {
    "craft_story": (
        "CRAFT STORY: one manufacturing or process decision, told end to end — "
        "what the problem was, what we do about it, and how we know it works. "
        "The reader should finish knowing something they could verify. This is "
        "the only content type on the whole site that a competitor cannot copy, "
        "because it is about OUR process, so do not waste it on generalities."
    ),
    "material_explainer": (
        "MATERIAL EXPLAINER: the trade-off behind a material or component "
        "choice. Name what the alternatives give up. A material page that only "
        "praises the chosen material is an advertisement; one that explains what "
        "it costs you is a reference."
    ),
    "testing": (
        "TESTING: what we test, how, and what the result was. State the method "
        "before the result — an untested claim and a tested one read identically "
        "unless the method is on the page."
    ),
    "buying_guide": (
        "BUYING GUIDE: how to choose in this category — the decision framework, "
        "not our catalogue. Cover the axes a buyer actually weighs and what each "
        "one costs them. Our products may appear only where they genuinely land "
        "in that framework, and only after the framework is complete."
    ),
    "wholesale_guide": (
        "WHOLESALE GUIDE: one purchasing decision a retail buyer must make "
        "(minimum order, private label, lead time, factory audit, payment "
        "terms). Write to someone spending their own money on inventory they "
        "have to sell. Concrete beats reassuring: a real number with its "
        "conditions is worth more than 'flexible' or 'competitive'. "
        "You are given `wholesale_policy_facts` — the actual, owner-approved "
        "terms (minimum order, freight, payment, defects, what we make "
        "in-house). USE THEM: a purchasing question answered with 'ask us' is "
        "not answered. NEVER state per-unit prices, and never promise a term "
        "that is not in those facts. If a term genuinely is not there, say so "
        "in `missing_facts` rather than inventing a reassuring version."
    ),
    "brand_story": (
        "BRAND STORY: who we are and why this factory exists — grounded in the "
        "supplied company facts only. No founder mythology, no invented "
        "milestones, no numbers that were not supplied."
    ),
}

_AUDIENCE_BRIEF = {
    "consumer": (
        "AUDIENCE: a shopper deciding whether this category is for them. They do "
        "not care who we are yet."
    ),
    "wholesale": (
        "AUDIENCE: a retail buyer or store owner evaluating us as a supplier. "
        "They are risking their own shelf space and cash. They care about "
        "reliability and terms, not features."
    ),
    "brand": (
        "AUDIENCE: someone who already found us and is deciding whether to trust "
        "us — a shopper checking we are real, or a buyer checking we can "
        "actually manufacture. Proof beats adjectives."
    ),
}


def seo_content_instruction(*, item_kind: str, audience: str) -> str:
    return (
        "You are writing ONE evergreen article for a manufacturer-owned DTC "
        "website. You are given: the topic, the target audience, verified CRAFT "
        "FACTS from our own factory, optionally product facts, and the site "
        "brand. Write the article.\n"
        "\n"
        + _AUDIENCE_BRIEF.get(audience, _AUDIENCE_BRIEF["consumer"])
        + "\n"
        + _KIND_BRIEF.get(item_kind, _KIND_BRIEF["buying_guide"])
        + "\n"
        "\n"
        "GROUNDING (absolute): every claim, number, and spec MUST come from the "
        "supplied facts. NEVER invent a number, a certification, a test result, "
        "a date, a headcount, a factory capability, or a competitor and its "
        "figures. If a fact is not supplied, do not mention it — and if that "
        "leaves the article thin, say so in `missing_facts` rather than filling "
        "the gap with something plausible.\n"
        "BRAND (absolute, 死命令): the ONLY brand you may ever name is the given "
        "`site_brand`. Never mention any third-party brand, manufacturer, or "
        "trademark.\n"
        "UNITS: US imperial only. Never output metric. Never output any "
        "non-English (CJK) text.\n"
        "NO commerce fields: never state price, stock, or shipping cost.\n"
        "\n"
        + ANSWER_THE_QUESTION_EN
        + "\n"
        + JUDGEMENT_STRUCTURE_EN
        + "\n"
        + ARITHMETIC_EN
        + "\n"
        "SHAPE: an editorial article, not a Q&A dump and not an essay. 4-7 H2 "
        "sections, each 2-5 sentences, each able to stand alone if an answer "
        "engine lifts it out — but together forming one argument with a "
        "beginning and an end. Do NOT pad to hit a length: an answer engine "
        "quotes a self-contained paragraph, never the 2,100th word of a "
        "long-form piece. Length follows from how much you actually know.\n"
        "\n"
        "INTERNAL LINKS: list what this article should link to in `link_intents` "
        "— use `product` for a product we make that genuinely belongs here, "
        "`guide` for a buyer-question guide on the same category, and "
        "`wholesale` when a consumer-side article touches something a trade "
        "buyer would care about (or vice versa). Give the INTENT, not a URL: "
        "the server resolves URLs at publish time, because the target page may "
        "not exist yet. Never invent a URL or an anchor to a page you were not "
        "told about.\n"
        "\n"
        "OUTPUT CONTRACT (mandatory — return ONLY a JSON object with EXACTLY "
        "this shape, no markdown, no prose outside the JSON):\n"
        "{\n"
        '  "item": {\n'
        '    "title": "<H1, specific, <=70 chars>",\n'
        '    "sections": [{"heading": "<H2>", "body": "<2-5 sentence plain-text '
        'paragraph, grounded>"}],\n'
        '    "seo": {"title": "<keyword-rich phrase, <=60 chars>", '
        '"meta_description": "<natural sentence <=160 chars>", "url_slug": '
        '"<lowercase-hyphenated-3-6-words>"},\n'
        '    "link_intents": [{"kind": "product|guide|wholesale", "hint": '
        '"<what it is about, e.g. a category path or a product type>"}],\n'
        '    "derived_numbers": [{"value": "2.4", "from": "5 / 2.11", "unit": '
        '"minutes"}]\n'
        "  },\n"
        '  "missing_facts": ["<what you needed and did not have; empty list if '
        'nothing>"]\n'
        "}"
    )


def seo_revise_instruction() -> str:
    """按批评重写一篇 SEO 文章——与 GEO 重写链同源的家规。"""
    return (
        "你要**重写一篇**已经生成的站内 SEO 文章。下面给你:这篇的现有内容、"
        "审稿模型对它的批评意见、以及**全部可用的真实事实**(工艺事实 / 产品事实)。\n"
        "\n"
        + NO_FABRICATION_ZH
        + "\n"
        "**品牌铁律**:唯一能出现的品牌是 `site_brand`,绝不提任何第三方品牌。"
        "所以「应该和其他品牌对比」这类批评**不能靠点名竞品来满足**——正确做法是"
        "对比**通用类型/做法**,或如实说明适用边界。\n"
        "\n"
        + ARITHMETIC_ZH
        + "\n"
        + ANSWER_THE_QUESTION_ZH
        + "\n"
        + JUDGEMENT_STRUCTURE_ZH
        + "\n"
        + NO_NAME_REPETITION_ZH
        + "\n"
        "**形状**:编辑体文章,4-7 个 H2,每段 2-5 句、能被单独摘走。"
        "**不许为了显得充实而加长**——注水段落会稀释真正有信息量的部分。\n"
        "\n"
        "其他要求同原稿:美制英制单位、纯英文(不出现中文)、不写价格/库存/运费。\n"
        "\n"
        "只返回 JSON,不要 markdown:\n"
        "{\n"
        '  "item": {"title":"...","sections":[{"heading":"...","body":"..."}],'
        '"seo":{"title":"...","meta_description":"...","url_slug":"..."},'
        '"link_intents":[{"kind":"product|guide|wholesale","hint":"..."}]},\n'
        '  "addressed": ["<用中文说明:这条批评你怎么改的>"],\n'
        '  "unaddressed": [{"critique":"<原批评>","reason":"<用中文说明为什么改不了>",'
        '"needs_data":true,"missing_fact":"<缺哪个数据;不缺数据则空字符串>"}]\n'
        "}\n"
        "注意:`seo.url_slug` 如果这篇已经发布过,**必须原样保留**——"
        "改地址等于把已积累的权重丢掉。"
    )


__all__ = [
    "SEO_CONTENT_SKILL_VERSION",
    "seo_content_instruction",
    "seo_revise_instruction",
]
