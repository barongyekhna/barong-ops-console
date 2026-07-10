from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).parent / "skills"

KEYWORD_RESEARCH_SKILL_VERSION = "k-keyword-research-independent-site-v1"
SELLING_POINTS_SKILL_VERSION = "k-selling-points-conversion-v1"

KEYWORD_RESEARCH_SKILL_SOURCES = [
    {
        "name": "Google Search Central SEO Starter Guide",
        "url": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
        "applied_as": "match product language to real audience queries and keep content useful for searchers",
    },
    {
        "name": "Ahrefs Keyword Research Guide",
        "url": "https://ahrefs.com/blog/keyword-research/",
        "applied_as": "use seed expansion, parent topics, traffic potential, keyword difficulty, and search intent",
    },
    {
        "name": "Semrush Ecommerce Keyword Research",
        "url": "https://www.semrush.com/blog/ecommerce-keyword-research/",
        "applied_as": "separate transactional, commercial, informational, and navigational ecommerce intent",
    },
]

SELLING_POINTS_SKILL_SOURCES = [
    {
        "name": "Nielsen Norman Group Ecommerce Product Pages",
        "url": "https://www.nngroup.com/articles/ecommerce-product-pages/",
        "applied_as": "answer shopper questions with clear product facts, options, and decision support",
    },
    {
        "name": "Baymard Institute Product Page UX Research",
        "url": "https://baymard.com/research/product-page",
        "applied_as": "prioritize images, variation clarity, compatibility, specs, and product page confidence signals",
    },
    {
        "name": "Google Search Central SEO Starter Guide",
        "url": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
        "applied_as": "write user-first product copy that reflects how the target market searches",
    },
]


def keyword_research_skill_context() -> dict[str, Any]:
    return {
        "version": KEYWORD_RESEARCH_SKILL_VERSION,
        "name": "Independent-site ecommerce keyword research skill",
        "goal": (
            "Build a buyer-intent keyword set for an independent ecommerce site, "
            "grounded in SERP evidence and safe enough for manual review."
        ),
        "serp_mining": [
            "Start from the product's main keyword, product facts, materials, dimensions, compatibility, target user, and use cases.",
            "Extract repeated terms from organic titles/snippets: category names, problem terms, feature modifiers, material/spec words, use-case phrases, and comparison terms.",
            "Generate long-tail variants with buyer modifiers such as best, for, with, replacement, kit, compatible, heavy duty, wholesale, price, near target-market language equivalents, and exact spec phrases when supported.",
            "Keep competitor and brand terms as evidence, but flag them as risk or restricted unless the product explicitly owns or can safely reference the brand.",
        ],
        "intent_model": [
            "transactional: ready-to-buy phrases, product + purchase/modifier/spec/commercial terms",
            "commercial_investigation: best/review/compare/alternative phrases with product fit",
            "problem_aware: pain/use-case phrases that can convert when mapped to product facts",
            "informational: how-to/definition queries; keep only when they expose strong product demand",
            "navigational_or_brand: brand/site names; reject or flag unless safe",
        ],
        "scoring": [
            "product_fit: keyword must match actual product type, use case, market, and variant data",
            "purchase_intent: prefer terms close to a buying decision over generic education",
            "specificity: prefer long-tail/spec/attribute terms over broad head terms",
            "serp_evidence: prefer terms appearing in SERP titles/snippets or provider keyword data",
            "differentiation: prefer modifiers tied to product strengths and uploaded/manual product facts",
            "localization: use the target market's normal wording, units, spelling, and language",
            "safety: reject prohibited, regulated, trademark, exaggerated, medical/legal, or unsupported claim terms",
        ],
        "output_contract": {
            "chatgpt": [
                "cleaned_keywords",
                "filtered_keywords",
                "rejected_keywords",
                "rationale",
            ],
            "claude": [
                "final_keywords",
                "high_value_keywords",
                "low_value_keywords",
                "risk_keywords",
            ],
        },
        "sources": KEYWORD_RESEARCH_SKILL_SOURCES,
    }


def selling_points_skill_context() -> dict[str, Any]:
    return {
        "version": SELLING_POINTS_SKILL_VERSION,
        "name": "Conversion-first ecommerce selling-points skill",
        "goal": (
            "Turn approved keywords and product facts into target-market copy that "
            "helps shoppers decide, without inventing claims."
        ),
        "copy_strategy": [
            "Use only supplied product facts, approved non-risk keywords, variant data, and manual product information.",
            "Convert feature -> advantage -> shopper outcome; every bullet must make a buying decision easier.",
            "Lead with the strongest customer-relevant benefit, then support it with proof: material, dimension, compatibility, quantity, use case, or process detail.",
            "Address likely objections: fit, compatibility, durability, installation/use, maintenance, packaging, and value.",
            "Use target-market language, spelling, units, and ecommerce phrasing; translate final copy to the market language.",
            "Avoid unsupported superlatives, medical/legal/safety promises, trademark misuse, and absolute guarantees.",
        ],
        "required_copy_blocks": [
            "benefit-led bullets ranked by conversion importance",
            "marketing_copy with a concise product-page paragraph",
            "translated_version in the target market language",
            "chinese_translation covering every final bullet and marketing_copy for operator review",
            "seo_keywords pulled from approved non-risk keywords",
            "market_tags for buyer segment, use case, and product type",
        ],
        "quality_bar": [
            "Specific beats generic; mention concrete product attributes whenever available.",
            "Do not repeat the same benefit with different wording.",
            "Prefer clear plain language over hype.",
            "Make missing proof explicit in rationale instead of fabricating details.",
        ],
        "sources": SELLING_POINTS_SKILL_SOURCES,
    }


def chatgpt_keyword_filter_instruction() -> str:
    return (
        "You are the first K-series ecommerce keyword strategist for an independent "
        "DTC/storefront site. Use the supplied keyword_research_skill exactly. "
        "Clean duplicates, normalize obvious language/unit variants for the target market, "
        "classify intent, and keep buyer-intent keywords that fit the actual product. "
        "Reject generic informational terms, unsupported claims, competitor/brand misuse, "
        "and terms that do not match product facts. Return only valid JSON with "
        "cleaned_keywords, filtered_keywords, rejected_keywords, and rationale. "
        "cleaned_keywords should preserve strong long-tail modifiers. filtered_keywords "
        "should be the best candidates for Claude final review. rejected_keywords may be "
        "strings or objects with keyword and reason. Do not include markdown or prose "
        "outside the JSON object."
    )


def claude_keyword_review_instruction() -> str:
    return (
        "You are the final K-series keyword reviewer and risk governor. Use the supplied "
        "keyword_research_skill exactly. Select high-intent, product-fit keywords from "
        "the ChatGPT candidate set, separate high_value_keywords from low_value_keywords, "
        "and identify risk_keywords for human review. final_keywords must contain at "
        "least three high-intent keywords when enough valid candidates exist. risk_keywords "
        "must be an array of objects with term and reason. Flag trademark, competitor, "
        "regulated, medical/legal/safety, exaggerated, adult, weapon, and unsupported "
        "claim terms. Return only valid JSON with final_keywords, high_value_keywords, "
        "low_value_keywords, and risk_keywords. Do not include markdown or prose outside "
        "the JSON object."
    )


def selling_points_instruction() -> str:
    return (
        "Generate conversion-first ecommerce selling points from the full product data. "
        "Use the supplied selling_points_skill exactly. Base every claim on product facts, "
        "approved keywords, variant data, or manual product information. Translate into "
        "the target market language and keep copy clear enough for a shopper to decide. "
        "Return only valid JSON with bullets, marketing_copy, translated_version, "
        "chinese_translation, target_language, seo_keywords, market_tags, and "
        "confidence_score. bullets must "
        "be ranked by importance_score and each bullet should include a concrete benefit "
        "or proof point. Do not include markdown or prose outside the JSON object."
    )


# --- P-series: file-backed copywriting + art-direction skills (Fable 5) -------
# These skills live as authored Markdown packages under ./skills/<name>/SKILL.md
# (+ references/). They are loaded verbatim and hashed so every generation can
# persist the exact skill version + content hash for audit (same discipline as
# the R/K inline skills above).

AMAZON_COPY_SKILL_VERSION = "k-amazon-listing-copywriting-v1"
DTC_COPY_SKILL_VERSION = "k-independent-site-seo-copywriting-v1"
IMAGE_ART_DIRECTION_SKILL_VERSION = "k-product-image-art-direction-v1"


def _load_skill_markdown(folder: str, filename: str = "SKILL.md") -> tuple[str, str]:
    """Return (markdown_body, sha256) for a file-backed skill package."""
    text = (_SKILLS_DIR / folder / filename).read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def amazon_copy_skill_context() -> dict[str, Any]:
    body, digest = _load_skill_markdown("amazon-listing-copywriting")
    return {
        "version": AMAZON_COPY_SKILL_VERSION,
        "name": "Amazon listing copywriting skill (A10 / COSMO / Rufus)",
        "channel": "amazon",
        "content_sha256": digest,
        "skill_markdown": body,
    }


def dtc_copy_skill_context() -> dict[str, Any]:
    body, digest = _load_skill_markdown("independent-site-seo-copywriting")
    return {
        "version": DTC_COPY_SKILL_VERSION,
        "name": "Independent-site SEO copywriting skill (Google 2025-2026 / AI Overviews)",
        "channel": "dtc",
        "content_sha256": digest,
        "skill_markdown": body,
    }


def copy_skill_context_for_channel(channel: str) -> dict[str, Any]:
    """Amazon products use the Amazon listing skill; everything else = DTC."""
    return amazon_copy_skill_context() if channel == "amazon" else dtc_copy_skill_context()


def image_art_direction_skill_context() -> dict[str, Any]:
    body, digest = _load_skill_markdown("product-image-art-direction")
    return {
        "version": IMAGE_ART_DIRECTION_SKILL_VERSION,
        "name": "Product image art-direction skill (copy -> image prompts)",
        "content_sha256": digest,
        "skill_markdown": body,
    }


def marketing_copy_instruction(channel: str) -> str:
    surface = "Amazon listing" if channel == "amazon" else "independent-site (DTC) product page"
    return (
        f"You are the K-series {surface} copywriter. Use the supplied copy skill "
        "(skill_markdown) exactly as the authoritative playbook, following its workflow "
        "and its 交付格式 (delivery format). Base every claim only on the supplied product "
        "facts, approved non-risk keywords, selling points, variant data, and manual "
        "product information; never fabricate specs, numbers, certifications, or reviews. "
        "Respect every 红线 (hard rule) in the skill. Return only valid JSON with the "
        "channel-appropriate copy blocks, a machine-usable structure per field, a "
        "compliance_self_check object, and a missing_inputs list for any claim you could "
        "not support. Do not include markdown or prose outside the JSON object."
    )


def image_art_direction_instruction() -> str:
    return (
        "You are the K-series product-image art director. First read the product's finished "
        "marketing copy, then use the supplied art-direction skill (skill_markdown) exactly. "
        "The product's real photo is the immutable reference (never regenerate the product "
        "body -- AI only handles background/scene/lighting). Return ONLY a valid JSON object "
        "with EXACTLY these keys (no markdown, no prose outside the JSON):\n"
        "{\n"
        '  "image_count": <integer = how many images the plan calls for>,\n'
        '  "channel": "amazon" | "dtc",\n'
        '  "aspect_ratio": "<e.g. 1:1 for Amazon main, 4:5, 16:9>",\n'
        '  "edit_mode": true,\n'
        '  "global_style": {"style": "<archetype + palette, English>",'
        ' "lighting": "<lighting language, English>",'
        ' "composition": "<composition/camera, English>",'
        ' "background": "<background/scene, English>"},\n'
        '  "main_prompt": "<ready-to-use English prompt for the hero/main image,'
        ' with the global STYLE BLOCK appended>",\n'
        '  "style_block": "<the reusable global STYLE BLOCK, English>",\n'
        '  "images": [{"position": <int>, "role": "<主图/白底副图/细节图/场景图/信息图/...>",'
        ' "placement": "gallery" | "description",'
        ' "mission": "<CTR/看懂/想要/...>", "prompt": "<English prompt for this image>",'
        ' "overlay_text": "<on-image text or empty>",'
        ' "title": "<image title for WordPress media, English>",'
        ' "alt": "<alt text: descriptive, SEO + accessibility, English, weave the'
        " product's real keywords in naturally, no stuffing>\","
        ' "caption": "<short on-page caption, English>",'
        ' "description": "<fuller image description for WordPress media, English>",'
        ' "note": "<中文制作备注>"}],\n'
        '  "consistency": "<seed/reference/product-detail checks>",\n'
        '  "compliance_checklist": ["<...>"],\n'
        '  "missing_assets": ["<what the user still needs to provide>"]\n'
        "}\n"
        "image_count MUST equal len(images). Every prompt must be English and grounded in the "
        "product facts + marketing copy; respect every 红线 in the skill.\n"
        "COVERAGE (do NOT be stingy on main/gallery images): plan GENEROUS gallery coverage "
        "with placement=gallery — a hero image + a clean white-background main + several "
        "detail/feature close-ups + lifestyle/scene shots (aim for 6-8 gallery images total, "
        "more for richer products). THEN add placement=description images (infographics / "
        "spec visuals / usage / size-in-context) as the copy sections need. "
        "gallery images go into the store's product image gallery; description images get "
        "embedded inside the product description at their position.\n"
        "SEO METADATA (mandatory, YOU write it — this is what goes on the live store): for "
        "EVERY image fill title + alt + caption + description in the target-market language "
        "(English for US). alt must describe the image accurately with the product's real "
        "keywords woven in naturally; never keyword-stuff; never fabricate features."
    )


def plain_chinese_instruction(label: str) -> str:
    return (
        f"把下面这份产品{label}(结构化 JSON)转述成通俗易懂的\u4eba\u8bdd\u4e2d\u6587\uff0c"
        "\u8ba9\u4e0d\u61c2\u82f1\u6587\u548c\u6280\u672f\u672f\u8bed\u7684\u4eba\u4e5f\u80fd\u770b\u61c2\u3002"
        "\u5206\u6bb5\u8bb2\u6e05\u695a\u6bcf\u4e00\u5757\u7684\u8981\u70b9\uff08\u6807\u9898/\u5356\u70b9/"
        "\u63cf\u8ff0/\u89c4\u683c/FAQ/\u56fe\u7247\u8ba1\u5212\u7b49\uff09\uff0c\u4fdd\u7559\u6240\u6709\u5173\u952e"
        "\u4fe1\u606f\u548c\u6570\u5b57\uff0c\u5e76\u5355\u72ec\u6307\u51fa\u8fd8\u7f3a\u54ea\u4e9b\u4fe1\u606f\u3002"
        "\u53ea\u8f93\u51fa\u4e2d\u6587\u6b63\u6587\uff0c\u4e0d\u8981\u8f93\u51fa JSON \u6216\u4ee3\u7801\u3002"
    )
