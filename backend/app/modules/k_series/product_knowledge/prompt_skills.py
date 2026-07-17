from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).parent / "skills"

KEYWORD_RESEARCH_SKILL_VERSION = "k-keyword-research-independent-site-v1"
SELLING_POINTS_SKILL_VERSION = "k-selling-points-evidence-v2"

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
            "Every bullet carries exactly one evidence reference: spec:<field>, verified_feature:<id>, or operator_fact.",
            "Every number in a bullet must appear verbatim in that one cited evidence snapshot; the package item count is the sole exception for a matching N-piece claim.",
            "Mention a concrete component such as kettle, pot, pan, or bowl only when it appears in package_includes or a component-specific structured-spec key.",
            "Use an N-piece claim only when package_includes exists and its list length is exactly N; otherwise describe it simply as a set.",
            "If no supplied evidence supports a proposed claim, omit it or mark it unverified for operator review; never phrase it as a product fact.",
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
        "bullet_contract": {
            "required_fields": [
                "id",
                "category",
                "text",
                "importance_score",
                "evidence",
                "evidence_excerpt",
                "verification_status",
            ],
            "evidence_enum": [
                "spec:<structured_specs_json field>",
                "verified_feature:<verified feature id>",
                "operator_fact",
            ],
            "verification_status": ["verified", "unverified"],
        },
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
        "must be an array of objects with term and reason; the reason MUST be written in "
        "简体中文 (Simplified Chinese) — it is read by a Chinese human reviewer deciding "
        "通过/拒绝, so state plainly 为什么这个词有风险 (e.g. 「包含无依据的加热功效声称，"
        "且带竞品品牌词」). Flag trademark, competitor, "
        "regulated, medical/legal/safety, exaggerated, adult, weapon, and unsupported "
        "claim terms. Return only valid JSON with final_keywords, high_value_keywords, "
        "low_value_keywords, and risk_keywords. Do not include markdown or prose outside "
        "the JSON object."
    )


def selling_points_instruction() -> str:
    return (
        "Generate evidence-backed candidate ecommerce selling points from the supplied "
        "evidence payload. Use the supplied selling_points_skill exactly. Product names, "
        "search keywords, and identity metadata identify the category but NEVER prove a "
        "claim. Base every claim only on `structured_specs_json`, a listed "
        "`verified_features` record, or an explicit `operator_facts` excerpt. Translate into "
        "the target market language. `structured_specs_json` contains raw verified evidence, "
        "while `structured_specs_buyer_display` contains server-converted buyer wording. For a "
        "US market, every buyer-visible measurement MUST use its exact imperial "
        "display_value/display_unit; never calculate conversions or expose raw metric wording. "
        "If a specification key is absent, omit that claim; never infer, estimate, or fill it. "
        "Every bullet MUST include an `evidence` string using exactly one of these "
        "forms: `spec:<field>`, `verified_feature:<id>`, or `operator_fact`, plus a "
        "short `evidence_excerpt` that contains the exact current supporting fact. Use "
        "`operator_fact` only when the same fact is explicitly present in `operator_facts`. "
        "Set `verification_status=verified` only when that "
        "reference exists in the supplied data. If no evidence supports a proposed "
        "claim, omit it or return it as `verification_status=unverified` for operator "
        "review; do not phrase unsupported content as a product fact. "
        "NUMBER RULE (absolute): every number in a bullet MUST appear verbatim in the "
        "single cited evidence value. Do not calculate, convert, round, or copy a number "
        "from identity/keyword text. A matching N-piece count may use "
        "`spec:package_includes` only when N exactly equals len(package_includes). "
        "COMPONENT RULE (absolute): mention kettle, pot, pan, bowl, or any other concrete "
        "included component only when it is named in `package_includes` or in a "
        "component-specific structured-spec key. Product names and keywords do not prove "
        "components. If package_includes is missing, never claim an N-piece count. "
        "TRANSLATION SIDECAR: when `customer_translation_requests` is non-empty, also "
        "return top-level `customer_translations`, one object per request, preserving the "
        "exact request_id. Translate only the supplied source text into buyer-facing "
        "English and fill exactly the requested label_en/value_en/package_includes keys; "
        "do not summarize, add components, convert units, or infer facts. "
        "Keep copy clear enough for a shopper to decide. "
        "Return only valid JSON with bullets, marketing_copy, translated_version, "
        "chinese_translation, target_language, seo_keywords, market_tags, and "
        "confidence_score. bullets must "
        "be ranked by importance_score; each bullet must contain id, category, text, "
        "importance_score, evidence, evidence_excerpt, and verification_status. Do not "
        "include markdown or prose outside the JSON object."
    )


# --- P-series: file-backed copywriting + art-direction skills (Fable 5) -------
# These skills live as authored Markdown packages under ./skills/<name>/SKILL.md
# (+ references/). They are loaded verbatim and hashed so every generation can
# persist the exact skill version + content hash for audit (same discipline as
# the R/K inline skills above).

AMAZON_COPY_SKILL_VERSION = "k-amazon-listing-copywriting-v1"
DTC_COPY_SKILL_VERSION = "k-independent-site-seo-copywriting-v1"
IMAGE_ART_DIRECTION_SKILL_VERSION = "k-product-image-art-direction-v3-evidence-proof"


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
    common = (
        f"You are the K-series {surface} copywriter. Use the supplied copy skill "
        "(skill_markdown) exactly as the authoritative playbook for HOW to write. "
        "Base every customer-facing claim ONLY on `selling_points_approved` and "
        "the exact `product.structured_specs_json` facts referenced by those approved "
        "points. The other product fields are neutral identity/record metadata, not a "
        "claim source. Ignore legacy descriptions, candidate selling points, and any "
        "marketing copy or SEO keywords embedded in a selling-point payload. Never "
        "fabricate specs, numbers, certifications, capabilities, or reviews. Respect every "
        "红线 (hard rule) in the skill.\n"
        "VERIFIED SPEC RULE (absolute): `product.structured_specs_json` is the raw "
        "evidence record, but ALL buyer-visible numeric wording must be copied only from "
        "`product.structured_specs_buyer_display.rows[].display_value/display_unit`. That "
        "server-owned field already contains US/imperial display conversions; never "
        "calculate or convert units yourself and never expose raw metric values to a US "
        "buyer. If a display row is absent, omit that specification everywhere; NEVER "
        "infer, estimate, round into a new claim, or copy an unsupported number from "
        "category expectations. Preserve the meaning of ranges.\n"
        "APPROVED-POINT RULE (absolute): every benefit, capability, use scenario, "
        "title modifier, bullet, and narrative claim must be traceable to one supplied "
        "approved point. Do not turn a neutral product name or search keyword into a "
        "claim. If the approved set does not support a statement, omit it.\n"
        "KEYWORD RULE: `final_keywords` is the risk-reviewed SEO wording set, never "
        "claim evidence. Put the primary keyword naturally in H1 and above-the-fold "
        "copy. Weave relevant long-tail keywords naturally into H2 section headings and "
        "their body copy; prioritize clarity and intent, never keyword-stuff or force an "
        "unsupported modifier.\n"
        "PACKAGE EVIDENCE RULE (absolute): `product.package_includes` is the canonical "
        "reviewed component list. A concrete component (for example kettle, pot, pan, or "
        "bowl) may appear in a title, bullet, or narrative only if it is named there or "
        "in a component-specific structured-spec key. A product name/keyword is not "
        "proof. Say N-piece only when package_includes exists and len(package_includes) "
        "equals N; otherwise say only 'set'. When the list exists, include a 'What's in "
        "the box' H2 block whose items exactly project that list without additions.\n"
        "BRAND RULE (absolute, overrides everything): the ONLY brand that may "
        "ever appear in ANY output field is the site's own brand given in "
        "`site_brand`. NEVER mention any third-party brand, manufacturer, or "
        "trademark — including anything in `forbidden_brand_terms` and any "
        "brand-looking token you infer from the product data. Write all copy "
        "brand-neutrally (e.g. 'this foldable yoga mat', never '<Brand> yoga "
        "mat'). In json_ld, brand is ALWAYS `site_brand`.\n"
        "CUSTOMER-FACING VOICE (this is SALES copy a shopper reads, not an "
        "internal report): write confident, benefit-first copy in second person "
        "('you'). Lead every section with what the buyer gets or feels, then "
        "support it with the facts you have. Paint concrete usage scenes. "
        "STRICTLY FORBIDDEN in any customer-facing field: meta-language and "
        "disclaimers such as 'not supplied', 'not provided', 'was not specified', "
        "'should be confirmed', 'must be verified', 'the product is described "
        "as', 'according to the supplied information', 'data was not available'. "
        "If a spec is missing, simply DON'T mention it on the page — report it "
        "ONLY in missing_inputs. Never turn a data gap into an FAQ or a caveat; "
        "FAQ answers must be confident and helpful, written from what you DO "
        "know. Still never fabricate: work only with supplied facts, but present "
        "them like a great salesperson, not a compliance auditor.\n"
        "OUTPUT CONTRACT (mandatory — downstream machines parse these exact keys; "
        "do NOT rename keys, do NOT use the skill's section numbering as keys): "
        "Return ONLY a valid JSON object with EXACTLY these top-level keys "
        "(no markdown, no prose outside the JSON):\n"
    )
    if channel == "amazon":
        return common + (
            "{\n"
            '  "channel": "amazon",\n'
            '  "listing_copy": {"title": "<Amazon title>",'
            ' "bullet_points": ["<5 bullets>"],'
            ' "product_description": "<paragraph text>",'
            ' "search_terms": ["<backend keywords>"]},\n'
            '  "a_plus_outline": [{"module": "<module type>", "purpose": "<...>",'
            ' "content": "<...>"}],\n'
            '  "compliance_self_check": {"<check>": "<pass/fail + why>"},\n'
            '  "missing_inputs": ["<unsupported claims you had to drop>"]\n'
            "}"
        )
    return common + (
        "{\n"
        '  "channel": "dtc",\n'
        '  "product_page_copy": {\n'
        '    "above_the_fold": {"headline": "<a HOOK about the buyer\'s outcome,'
        " NOT the product name repeated>\", \"subheadline\": \"<支撑句>\","
        ' "short_description": "<2-3 sentence lead selling the core benefit,'
        ' plain text>"},\n'
        '    "key_bullets": ["<benefit bullet: outcome first, fact second;'
        ' punchy, <=14 words>", "... 4-6 bullets"],\n'
        '    "chunk_sections": [{"heading": "<H2: a buyer-desire theme with a relevant'
        ' final keyword woven in naturally, e.g.'
        " 'Practice anywhere, store it in seconds' — NEVER questionnaire-style"
        " headings like 'Who is it for?'>\", \"body\": \"<2-4 sentence"
        ' paragraph: concrete scene + benefit + supporting fact, plain text>"}],\n'
        '    "specifications_html_table": "<table>...</table> ONLY with real'
        ' supplied specs (empty string if none — never fill with placeholders)",\n'
        '    "conversion_support_block": "<a short trust/decision paragraph: who'
        " this is perfect for + what makes buying easy — NO price/shipping"
        ' promises>"\n'
        "  },\n"
        '  "page_faq": [{"question": "<a real pain-point question supported by'
        ' faq_research>", "answer": "<confident, evidence-bounded, 1-3 sentences>",'
        ' "evidence_refs": ["<one or more exact faq_research.sources[].id values>"],'
        ' "intent_cluster": "<the matching faq_research intent_cluster>"}],\n'
        '  "json_ld": {"data": {"@type": "Product", "name": "<...>", "description":'
        ' "<...>", "brand": {"@type": "Brand", "name": "<site_brand, NEVER any'
        ' other brand>"}}},\n'
        '  "seo": {"title": "<meta title>", "meta_description": "<...>",'
        ' "h1": "<...>", "url_slug": "<lowercase, hyphenated, 3-5 meaningful words>"},\n'
        '  "compliance_self_check": {"<check>": "<pass/fail + why>"},\n'
        '  "missing_inputs": ["<unsupported claims you had to drop>"]\n'
        "}\n"
        "HARD RULES for the body copy: chunk_sections is the main narrative "
        "(3-5 sections, each a distinct buyer desire: quality/durability, "
        "use scenarios, convenience, fit/size confidence, care...); all copy "
        "fields are plain text except specifications_html_table; NEVER mention "
        "price/stock/shipping in any copy field (those are structured fields on "
        "the store — duplicating them in prose creates feed/page inconsistency). "
        "FAQ RULE (absolute): use only `faq_research.sources` and cite their exact IDs; "
        "cover distinct real buyer-concern clusters, never restate a basic specification "
        "as a question, and return an empty page_faq when research is insufficient. "
        "Serper evidence proves that the question is real; answers still may contain only "
        "facts supported by approved selling points/structured specs or cautious general "
        "guidance already present in the cited snippets. FAQ answers must answer with "
        "advice, method, or tradeoffs and MUST NOT repeat any product-specific numeric "
        "value from structured_specs_json (including dimensions, weight, capacity, or "
        "piece count); use qualitative wording such as 'nests compactly' and leave exact "
        "numbers to the specifications table."
    )


def image_art_direction_instruction() -> str:
    return (
        "You are the K-series product-image art director. Treat `selling_points_approved` "
        "as the ONLY authority for visual marketing claims, then use the supplied "
        "art-direction skill (skill_markdown) exactly. Product facts and verified "
        "structured specs may support composition and programmatic overlays, but candidate "
        "or marketing-copy claims are not inputs. "
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
        '  "images": [{"position": <int>, "role": "main" | "proof_scene" |'
        ' "dimension" | "feature_callout" | "spec" | "accessory" | "detail",'
        ' "placement": "gallery" | "description",'
        ' "aspect_ratio": "<THIS image\'s ratio, machine-readable like 1:1 / 4:5 / 16:9>",'
        ' "mission": "<CTR/看懂/想要/...>", "prompt": "<English prompt for this image>",'
        ' "selling_point_index": <1-based index in selling_points_approved, or null>,'
        ' "selling_point_id": "<exact approved point id, or null>",'
        ' "selling_point_text": "<exact approved point text, or null>",'
        ' "proof_intent": "<visible action/detail that proves that one point, or null>",'
        ' "overlay": null | {"schema_version": "k-info-overlay-v1",'
        ' "role": "feature_callout" | "dimension" | "spec", "items": ['
        '{"type": "callout", "source_field": "<structured_specs_json path>",'
        ' "anchor": {"x": <0..1>, "y": <0..1>},'
        ' "text_anchor": {"x": <0..1>, "y": <0..1>},'
        ' "leader_direction": "auto" | "left" | "right" | "up" | "down"}'
        ' | {"type": "dimension", "source_field": "dimensions.<length|width|height>",'
        ' "line": {'
        '"start": {"x": <0..1>, "y": <0..1>},'
        ' "end": {"x": <0..1>, "y": <0..1>}},'
        ' "text_anchor": {"x": <0..1>, "y": <0..1>}}]},'
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
        "image_count MUST equal len(images). Every prompt must be English and grounded in "
        "product facts plus the approved selling-point set; respect every 红线 in the skill.\n"
        "EVIDENCE BINDING (absolute): every proof_scene/accessory/detail image must bind "
        "EXACTLY ONE supplied approved point using its exact selling_point_id (and matching "
        "1-based index/text), then state a concrete proof_intent that is visibly photographable. "
        "Never bind an unapproved/candidate point and never add a second implied claim. "
        "feature_callout/spec/dimension instead require a verified structured overlay; if "
        "neither binding is available, omit the image.\n"
        "COVERAGE: position 1 MUST be the one and only role=main image: the product alone, "
        "centered, on a clean pure-white background, no props, no people, no overlay text, "
        "filling ~85% of the frame (this becomes the store's main image and the feed "
        "image). There must be NO white-background secondary role. Every position 2+ must "
        "be a proof shot in active real use, a verified information image, a dimension "
        "image, an accessory proof, or an evidence-bound detail — never decorative posing. "
        "For products used in cooking/camping, show real ignition/cooking/steam and a real "
        "camp environment when those approved points exist; lighting, contact shadows and "
        "depth must physically integrate product and scene. "
        "gallery images go into the store's product image gallery; description images get "
        "embedded inside the product description at their position. All gallery images "
        "are square 1:1. role=dimension is ALWAYS placement=gallery. If verified "
        "product.structured_specs_json.dimensions exist, the plan MUST include at least "
        "one role=dimension image; omission makes the entire brief invalid.\n"
        "SEO METADATA (mandatory, YOU write it — this is what goes on the live store): for "
        "EVERY image fill title + alt + caption + description in the target-market language "
        "(English for US). alt must describe the image accurately with the product's real "
        "keywords woven in naturally; never keyword-stuff; never fabricate features.\n"
        "BRAND RULE (absolute): NEVER put any third-party brand name, manufacturer, or "
        "trademark into ANY field (prompt / title / alt / caption / "
        "description) — including anything in `forbidden_brand_terms`. Refer to the product "
        "generically. Every image prompt MUST instruct the renderer to remove any brand "
        "logo or brand text visible on the reference product (replace with clean unbranded "
        "surface, keeping shape/color/structure). Overlay items must never contain "
        "free-form text.\n"
        "PROGRAMMATIC OVERLAY RULE (absolute): feature_callout, dimension, and spec images "
        "are clean BASE images. The image model must render NO text, letters, numbers, "
        "badges, arrows, leader lines, or measurement lines; leave uncluttered negative "
        "space at the overlay coordinates. Supply the exact structured `overlay` object "
        "instead. Every `source_field` MUST resolve to an existing value in "
        "product.structured_specs_json (for example lumens, ip_rating, "
        "dimensions.height); labels are server-owned, so never emit `label`, `text`, or "
        "a value field, and never infer a missing field. Use overlay=null for all other "
        "images. Overlay coordinates are only intent hints: the compositor detects the "
        "actual rendered foreground bounds and snaps dimension lines to the product edges. "
        "For a US target market, the compositor converts verified cm/kg values to inch/lb; "
        "never type or calculate those values in the prompt. If there are no verified "
        "fields for an infographic, use an approved-point-bound detail/usage proof instead."
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
