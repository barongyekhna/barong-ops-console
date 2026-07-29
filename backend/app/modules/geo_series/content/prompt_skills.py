"""GEO content generation prompt.

Unlike K's product-page copy, this produces **AI-citable topical content**: self-
contained question→answer blocks, generic-type comparisons, and use-case scenarios
that answer engines (ChatGPT / Perplexity / Google AI Overviews) can lift into an
answer. Every piece names the product (SITE_BRAND only) and records which products
it should internal-link to — Rail 1: content carries the product + link into the
answer so the reader can reach the PDP.
"""

from __future__ import annotations

GEO_CONTENT_SKILL_VERSION = "geo-content-v2"


def geo_content_instruction() -> str:
    return (
        "You are writing EVERGREEN, AI-citable guide content for a DTC brand's own "
        "website — the kind an AI answer engine (ChatGPT, Perplexity, Google AI "
        "Overviews) quotes when a shopper asks a question. You are given a topic "
        "(a product category), the category path, the site brand, and one or more "
        "of the brand's own products with their VERIFIED facts (buyer-display specs, "
        "approved selling points, what's-in-the-box). Produce a cluster of guide "
        "pieces about this topic.\n"
        "\n"
        "GROUNDING (absolute): every claim, number, and spec MUST come from the "
        "supplied product facts. NEVER invent a number, a specification, or a "
        "competitor product and its figures. If a fact is not supplied, do not "
        "mention it. Comparisons may only contrast GENERIC types or approaches "
        "(e.g. 'electric pump vs manual vs gravity camping showers') or the "
        "product's own variants — never a named third-party brand or fabricated "
        "rival specs.\n"
        "BRAND (absolute, 死命令): the ONLY brand you may ever name is the given "
        "`site_brand`. Never mention any third-party brand, manufacturer, or "
        "trademark. Refer to the product as e.g. 'the <site_brand> <product type>'.\n"
        "MECHANISM TRUTH: answer according to how THIS product actually works from "
        "its facts, never generic category behaviour that contradicts it.\n"
        "UNITS: US imperial only (the supplied facts are already imperial). Never "
        "output metric. Never output any non-English (CJK) text.\n"
        "NO commerce fields: never state price, stock, or shipping in the copy.\n"
        "\n"
        "CITABILITY (this is the whole point): write self-contained, extractable "
        "chunks. Each answer must fully answer its question in 2-4 sentences WITHOUT "
        "needing the rest of the page. Lead question-shaped. Name the product so an "
        "AI can attribute and recommend it, and list its identifier in "
        "`source_products` so we can internal-link it to its product page.\n"
        "\n"
        "ARITHMETIC IS ALLOWED — BUT SHOW YOUR WORK. You may compute a number the "
        "facts imply (\"5 gallons at 2.11 GPM lasts about 2.4 minutes\"), and you "
        "SHOULD when the question asks for one — but every computed number MUST be "
        "declared in `derived_numbers` as {\"value\": \"2.4\", \"from\": "
        "\"5 / 2.11\", \"unit\": \"minutes\"}. Each operand must come from the "
        "product facts or from the question itself; the server re-runs the "
        "arithmetic and rejects the piece if it does not check out. Do NOT round a "
        "number into vagueness to avoid declaring it — precision is the point.\n"
        "\n"
        "ANSWER THE QUESTION — DO NOT DESCRIBE THE PRODUCT. A question is answered "
        "when a reader who has NOT made up their mind can now make it up. Reciting "
        "the product's specifications is NOT an answer to a judgement question; it "
        "is a product description wearing a question as a hat. Specs are evidence "
        "FOR a judgement, never a substitute for one. If you find yourself listing "
        "what the product has, stop and write what that means for the reader's "
        "decision instead.\n"
        "\n"
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
        "\n"
        "REQUIRED QUESTIONS (when `required_questions` is non-empty): these are REAL "
        "buyer questions drawn from search demand and are SERVER-OWNED. You MUST "
        "write content that answers them. For the `qa` item, its `answer_blocks` "
        "MUST copy each required question's text EXACTLY (verbatim) and answer it — "
        "do NOT invent, reword, split, or add your own questions. Weave the same "
        "questions into the hub/comparison/scenario pieces wherever they fit. If "
        "`required_questions` is empty, derive sensible buyer questions from the "
        "product facts yourself.\n"
        "\n"
        "INCREMENTAL WRITING: `existing_content` lists pieces that already exist in "
        "this cluster and are being KEPT, and `skip_item_types` lists the item_types "
        "they occupy. You MUST NOT produce any item_type listed in `skip_item_types` "
        "— that slot is taken. Write only what is missing, and make it COMPLEMENT the "
        "existing pieces rather than repeat their angle. Likewise, never re-answer a "
        "question an existing piece already answers.\n"
        "\n"
        "WHAT TO PRODUCE: `produce_item_types` lists EXACTLY the item_types you "
        "must return — the server has already removed the slots that are taken. "
        "Return one item per listed type, EXCEPT `question_answer`, of which you "
        "return ONE PER pending required question. Never return an item_type that "
        "is not in that list, and never invent an item_type or a response shape of "
        "your own.\n"
        "\n"
        "The types mean: `question_answer` (one article answering exactly ONE "
        "answering exactly ONE required question, in depth, titled as that "
        "question — this is the type "
        "that wins specific searches), `hub` (one topic overview / how-to-choose), "
        "`how_it_works` (how this kind of product works, grounded in THIS product's "
        "mechanism), `comparison` (generic types/approaches or the product's "
        "variants), `scenario` (concrete use-cases the facts support), `qa` (a "
        "cluster of buyer question→answer blocks). Quality over quantity.\n"
        "\n"
        "OUTPUT CONTRACT (mandatory — return ONLY a JSON object with EXACTLY this "
        "shape, no markdown, no prose outside the JSON):\n"
        "{\n"
        '  "content_items": [\n'
        "    {\n"
        '      "item_type": "hub|how_it_works|comparison|scenario|qa|question_answer",\n'
        '      "title": "<question- or topic-shaped H1, <=70 chars>",\n'
        '      "sections": [{"heading": "<H2>", "body": "<2-4 sentence plain-text '
        'paragraph, grounded>"}],\n'
        '      "answer_blocks": [{"question": "<a real buyer question>", "answer": '
        '"<self-contained 2-4 sentence answer, grounded, names the product>"}],\n'
        '      "seo": {"title": "<keyword-rich phrase | ' " " '<=60 chars>", '
        '"meta_description": "<natural sentence <=160 chars>", "url_slug": '
        '"<lowercase-hyphenated-3-6-words>"},\n'
        '      "source_products": ["<the product_key/sku values this piece names '
        'and should link to>"],\n'
        '      "derived_numbers": [{"value": "2.4", "from": "5 / 2.11", "unit": '
        '"minutes"}]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Use `sections` for narrative pieces (hub/how_it_works/comparison/scenario) "
        "and `answer_blocks` for `qa`; a piece may use whichever fits. Every piece "
        "must reference at least one product in `source_products`."
    )


def geo_product_spotlight_instruction() -> str:
    """One article for a differentiated product inside a shared topic cluster.

    Same-category products share a cluster (never duplicate clusters), so this is
    how a genuinely distinct product — a panda-shaped shower next to the plain one
    — keeps its own story without splitting the topic.
    """
    return (
        "You are writing ONE guide article about a SPECIFIC product that sits "
        "inside a broader topic cluster on the brand's own website. The cluster "
        "already covers the shared basics (how this kind of product works, how to "
        "choose, use cases). Your job is DIFFERENT: explain what makes THIS "
        "product distinct from the others in the same category, and who it is for.\n"
        "\n"
        "You are given the topic, the product's own verified facts, and "
        "`sibling_products` (the other products in the same cluster) for contrast.\n"
        "\n"
        "GROUNDING (absolute): every claim, number, and spec MUST come from the "
        "supplied facts. NEVER invent a number, a specification, or a competitor. "
        "Contrast ONLY against the supplied sibling products or generic types — "
        "never a named third-party brand.\n"
        "BRAND (absolute): the ONLY brand you may name is the given `site_brand`.\n"
        "Do not repeat the cluster's shared how-it-works explanation at length — "
        "lead with the difference. Don't restate the whole spec sheet; the "
        "specifications table carries the numbers. US imperial only, English only, "
        "no price/stock/shipping.\n"
        "\n"
        "CITABILITY: write self-contained, extractable paragraphs. Name the product "
        "so an AI can attribute and recommend it, and put its identifier in "
        "`source_products` so we can internal-link it to its product page.\n"
        "\n"
        "OUTPUT CONTRACT (return ONLY this JSON object, no markdown):\n"
        "{\n"
        '  "content_items": [\n'
        "    {\n"
        '      "item_type": "product_spotlight",\n'
        '      "title": "<what makes this one different, <=70 chars>",\n'
        '      "sections": [{"heading": "<H2>", "body": "<2-4 sentence grounded '
        'paragraph>"}],\n'
        '      "answer_blocks": [{"question": "<a buyer question specific to this '
        'variant>", "answer": "<self-contained 2-4 sentence grounded answer>"}],\n'
        '      "seo": {"title": "<keyword-rich | <=60 chars>", "meta_description": '
        '"<<=160 chars>", "url_slug": "<lowercase-hyphenated-3-6-words>"},\n'
        '      "source_products": ["<this product\'s key/sku>"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Return EXACTLY ONE item."
    )


def geo_revise_instruction() -> str:
    """Rewrite one piece against its review critique — without inventing facts.

    The critique comes from a reviewer model reading the piece. Some of it is
    actionable (tone, balance, structure); some of it asks for facts the product
    data simply does not contain. Honouring the latter would mean fabricating a
    spec — the exact failure every guard in this pipeline exists to prevent — so
    the model must refuse it explicitly and say what data is missing instead.
    """
    return (
        "你要**重写一篇**已经生成的站内导购内容。下面给你:这篇的现有内容、审稿模型"
        "对它的批评意见、以及这个产品**全部可用的真实事实**。\n"
        "\n"
        "**最高铁律:绝不编造事实。**只能用给你的事实。如果某条批评要求补充一个"
        "事实里没有的数据(例如「应说明推荐充电功率」但规格里根本没有功率),"
        "**绝对不许瞎编一个数字或说法来满足它**——把这条批评放进 `unaddressed`,"
        "说明缺什么数据。宁可不改,也不许造假。\n"
        "\n"
        "**品牌铁律**:唯一能出现的品牌是 `site_brand`,绝不提任何第三方品牌。"
        "所以「应该和其他品牌对比」这类批评**不能靠点名竞品来满足**——正确做法是"
        "对比**通用类型/做法**(如电动 vs 手动 vs 重力),或如实说明本产品的适用边界。\n"
        "\n"
        "可以照做的批评通常是:语气过于自夸、缺少客观性、没提适用局限、结构不利于"
        "被摘录、答案不够自足。这些请**在事实范围内**认真改。\n"
        "\n"
        "**算术是允许的,但必须亮算式。**可以算出事实蕴含的数字(如「5 加仑按 "
        "2.11 GPM 约 2.4 分钟」),问句要答案时**就该算**;但每个算出来的数字必须"
        "在 `derived_numbers` 里声明 {\"value\":\"2.4\",\"from\":\"5 / 2.11\"},"
        "每个操作数要么来自产品事实、要么来自问句本身。服务端会重算一遍,对不上"
        "就整篇打回。**不许为了躲开声明而把数字含糊掉**——精确才是价值所在。\n"
        "\n"
        "**回答问句,不要介绍产品。**一个问题被回答的标准是:还没拿定主意的读者"
        "读完能拿定主意。罗列产品参数**不构成**对判断题的回答——那是「产品介绍"
        "戴了个问句的帽子」。参数是判断的**证据**,不是判断本身。如果原稿主要在"
        "堆参数,这次重写必须改成讲清楚**这些参数对读者的决定意味着什么**。\n"
        "\n"
        "**判断类问句**(值不值/要不要买/好不好/该选哪个)必须写成决策结构:"
        "①第一句给条件式结论(Yes, if… / Not really, if…);②什么情况下值得,"
        "每条挂在机制或真实事实上;③**什么情况下不值得——这半边是强制的**;"
        "④最后才说本产品落在这个框架的哪里。说「如果营地本来就有淋浴房则价值"
        "不大」**没有编造任何东西**,它是条件判断不是事实主张,所以不受"
        "「绝不编造」约束。**「不值得」那一段里不许出现推销语言、不许拐回产品"
        "收尾**——一段专门讲别买的文字以推销结尾,就等于自毁可信度。\n"
        "\n"
        "**别每句话都写产品全称**。第一次点名后改用简称或代词,句句全称读起来"
        "很生硬,也会挤掉真正有信息量的内容。\n"
        "\n"
        "其他要求同原稿:美制英制单位、纯英文(不出现中文)、不写价格/库存/运费、"
        "问答要自足可摘录、点名产品并在 `source_products` 里给出标识。\n"
        "\n"
        "只返回 JSON,不要 markdown:\n"
        "{\n"
        '  "item": {"item_type":"<保持与原稿一致>","title":"...",'
        '"sections":[{"heading":"...","body":"..."}],'
        '"answer_blocks":[{"question":"...","answer":"..."}],'
        '"seo":{"title":"...","meta_description":"...","url_slug":"..."},'
        '"source_products":["..."]},\n'
        '  "addressed": ["<用中文说明:这条批评你怎么改的>"],\n'
        '  "unaddressed": [{"critique":"<原批评>","reason":"<用中文说明为什么改不了>",'
        '"needs_data":true,"missing_fact":"<缺哪个数据,如「充电功率」;不缺数据则空字符串>"}]\n'
        "}\n"
        "注意:`answer_blocks` 里的问句如果原稿是运营者选定的真实买家问题,"
        "**必须逐字保留**,只改答案。"
    )


__all__ = [
    "geo_content_instruction",
    "geo_product_spotlight_instruction",
    "geo_revise_instruction",
    "GEO_CONTENT_SKILL_VERSION",
]
