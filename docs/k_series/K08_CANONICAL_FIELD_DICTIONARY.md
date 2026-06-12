# K08 Canonical Field Dictionary

Status: K08A field dictionary draft, pending owner review.

Date: 2026-06-12.

## 1. 字典使用规则

This dictionary defines the canonical K08 field baseline for future K07, K09, K10, K12, K15, K20 and K28/P-series consumption through the Barong backend API.

Column meanings:

- `Required level` uses the K08 required-level vocabulary defined in `K08_REQUIRED_OPTIONAL_FIELD_MATRIX.md`.
- `Source of truth` means the authority after review. AI draft fields can exist, but reviewed canonical fields win.
- `AI can auto-write?` means AI can write without human review. For canonical business fields the answer is no.
- `Used by downstream` names likely future consumers and does not enable those consumers in K08A.

## 2. System / identity

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `id` | Product row ID | System / identity | Stable database identity | UUID | system_generated | System | no | no, system only | no | no | K API, all downstream | K-owned product row identifier. |
| `workspace_key` | Workspace key | System / identity | Adapter-pending workspace boundary | text | required_at_creation | System / owner config | no | no, system only | no | no | K API, access shim | Default `default_independent_store` until formal scope. |
| `business_context` | Business context | System / identity | Adapter-pending business context | text | required_at_creation | System / owner config | no | no, system only | no | no | K API, access shim | Default `independent_store`. |
| `scope_mode` | Scope mode | System / identity | Marks adapter-pending behavior | enum/text | required_at_creation | System / owner config | no | no, system only | no | no | K API, access shim | Default `adapter_pending`. |
| `product_key` | Product key | System / identity | Stable human-facing K identifier | text | required_at_creation | Operator / owner | yes | no | yes | yes | K07, K API, all downstream | Must be unique inside workspace and business context. |
| `source_system` | Source system | Source / import | Source channel such as manual, imported, future API, or future Barong intake | text/enum | required_at_creation | Operator / system | yes | no | yes if imported | yes | K07, K10, audit context | Default may be `manual`; this marks origin and does not make Google Sheets a long-term source of truth. |
| `source_record_id` | Source record ID | Source / import | External row or record reference | text | optional | Operator / system | no | no | conditional | yes | Import reconciliation | Not a long-term source of truth. |
| `sku` | SKU | System / identity | Sellable SKU identifier | text | required_before_woo_draft | Operator / reviewer | no | no | yes | yes | Woo draft, catalog, P-series | Must be reviewed before commerce usage. |
| `parent_product_id` | Parent product | System / identity | Parent row for variants | UUID | conditional | Operator / reviewer | yes | no | yes when variants | yes | K07, Woo draft, catalog | K product self-reference. |
| `variant_group_key` | Variant group | System / identity | Groups variants together | text | conditional | Operator / reviewer | yes | no | yes when variants | yes | K07, Woo draft, catalog | Required when variant grouping is used. |
| `product_status` | Product status | Readiness / lifecycle | Product lifecycle state | enum/text | required_at_creation | Operator / reviewer | yes | no | yes | yes | K07, readiness, K API | Suggested values follow K04/K06 lifecycle. |
| `review_status` | Review status | Readiness / lifecycle | Human review lifecycle state | enum/text | required_at_creation | Reviewer / owner | yes | no | yes | yes by reviewer | K07, K12, readiness | Draft values cannot be treated as approved. |
| `canonical_language` | Canonical language | System / identity | Primary record language | text | required_at_creation | System / owner config | no | no, system only | no | no | K10, K12, P-series | Default `en`. |
| `created_by_user_id` | Created by | System / identity | User trace for creation | UUID | system_generated | System | no | no, system only | no | no | K21, review evidence | Stored by value during adapter-pending. |
| `updated_by_user_id` | Updated by | System / identity | User trace for latest update | UUID | system_generated | System | no | no, system only | no | no | K21, review evidence | Stored by value during adapter-pending. |
| `created_at` | Created at | System / identity | Creation timestamp | timestamptz | system_generated | System | no | no, system only | no | no | K API, sorting, audit context | Required on K tables. |
| `updated_at` | Updated at | System / identity | Last update timestamp | timestamptz | system_generated | System | no | no, system only | no | no | K API, sorting, audit context | Required on K tables. |

## 3. Canonical English

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `product_name_en` | Product name | Canonical English | Canonical English product name | text | required_before_keyword_research | Operator / reviewer | yes | no | yes | yes | K07, K10, K12, K15, Woo draft, P-series | Primary English product label. |
| `brand_name` | Brand name | Canonical English | Brand identity | text | conditional | Operator / reviewer | yes | no | yes if branded | yes | K07, category, Woo draft | Required when product is branded. |
| `manufacturer` | Manufacturer | Canonical English | Manufacturer identity | text | optional | Operator / reviewer | yes | no | conditional | yes | Catalog, compliance | Do not infer if absent. |
| `product_type` | Product type | Canonical English | Normalized product type | text | required_before_keyword_research | Operator / reviewer | yes | no | yes | yes | K07, K15, K09, category, Woo draft | Can be suggested from raw input, then reviewed. |
| `short_description_en` | Short description | Canonical English | Short English product summary | text | required_before_woo_draft | Operator / reviewer | yes | no | yes | yes | K07, K12, content, Woo draft | Must avoid unsupported claims. |
| `long_description_en` | Long description | Canonical English | Long English product description | text | required_before_woo_draft | Operator / reviewer | yes | no | yes | yes | K07, K12, content, Woo draft, P-series | Can use a page content source placeholder before final copy. |
| `primary_use_case_en` | Primary use case | Canonical English | Main use scenario | text | required_before_keyword_research | Operator / reviewer | yes | no | yes | yes | K15, category, content | AI may refine wording from provided facts only. |
| `target_customer_en` | Target customer | Canonical English | Target buyer or user | text | required_before_page_blueprint | Operator / reviewer | yes | no | yes | yes | K15, content, P-series | Should stay factual and market-aware. |

## 4. Raw input

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `raw_input_text` | Raw input text | Raw input | Preserve original operator or supplier text | text | required_at_creation | Operator / importer | no | no | no for preservation | yes | K10, K12, review evidence | Required unless `product_name_en` creation path is explicitly accepted. |
| `raw_input_language` | Raw input language | Raw input | Original input language | text | required_at_creation | Operator / reviewer | yes | no | yes | yes | K10, K13 | If `raw_input_text` exists, preserve the original language code or owner-approved unknown value; if creation uses only `product_name_en`, default may be `en`; K10/K13 depend on it for translation and checks. |
| `raw_input_payload_json` | Raw input payload | Raw input | Preserve structured source payload | jsonb | optional | Operator / importer | no | no | conditional | yes | K10, import reconciliation | Do not store secrets or credential-like data. |

## 5. Commercial

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `regular_price` | Regular price | Commercial | Base selling price | decimal | required_before_woo_draft | Operator / owner | no | no | yes | yes | Woo draft, publish review | May use an approved price policy placeholder before draft. |
| `sale_price` | Sale price | Commercial | Sale price if applicable | decimal | optional | Operator / owner | no | no | yes if present | yes | Woo draft, publish review | Must not imply misleading discount. |
| `price_currency` | Price currency | Commercial | Currency code for price fields | text | required_before_woo_draft | Operator / owner | no | no | yes | yes | Woo draft, catalog | Example `USD`; default currency requires owner decision. |
| `cost` | Cost | Commercial | Internal cost | decimal | optional | Operator / owner | no | no | yes if used | yes, restricted | Internal reporting | Not publish-facing by default. |
| `margin` | Margin | Commercial | Internal margin | decimal | optional | Operator / owner | no | no | yes if used | yes, restricted | Internal reporting | Can be derived later, but K08A implements nothing. |
| `stock_status` | Stock status | Commercial | In stock, out of stock, or managed status | enum/text | required_before_woo_draft | Operator / owner | no | no | yes | yes | Woo draft, K07 | Required before commerce draft. |
| `inventory_quantity` | Inventory quantity | Commercial | Managed stock quantity | integer | conditional | Operator / owner | no | no | yes if managed | yes | Woo draft, K07 | Required when `manage_stock` is true. |
| `manage_stock` | Manage stock | Commercial | Whether inventory is tracked | boolean | required_before_woo_draft | Operator / owner | no | no | yes | yes | Woo draft | Controls quantity requirement. |
| `moq` | MOQ | Commercial | Minimum order quantity | integer/decimal | optional | Operator / supplier | no | no | yes if used | yes | B2B, content | Do not infer from product type. |
| `lead_time` | Lead time | Commercial | Fulfillment or procurement lead time | text/interval | optional | Operator / supplier | no | no | yes if used | yes | B2B, Woo notes | Needs explicit source. |
| `shipping_class` | Shipping class | Commercial | Shipping classification | text | conditional | Operator / owner | no | no | yes if used | yes | Woo draft | May depend on dimensions and weight. |
| `tax_class` | Tax class | Commercial | Tax classification | text | conditional | Operator / owner | no | no | yes if used | yes | Woo draft | Must not be AI-inferred. |

## 6. Dimensions / weight

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `dimensions_json` | Product dimensions | Dimensions / weight | Product dimensions with original and normalized units | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | K09, Woo draft, media, content | Required when shipping/display needs dimensions. |
| `package_dimensions_json` | Package dimensions | Dimensions / weight | Packaged dimensions | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | K09, Woo draft, shipping | Required when shipping requires it. |
| `weight_json` | Product weight | Dimensions / weight | Product weight with original and normalized units | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | K09, Woo draft, shipping | AI must not guess missing values. |
| `package_weight_json` | Package weight | Dimensions / weight | Packaged weight | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | K09, Woo draft, shipping | Preserve source and conversion precision. |

## 7. Product facts

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `materials_json` | Materials | Product facts | Materials and composition | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | Category, content, risk review | Must be provided or reviewed source data. |
| `color_options_json` | Color options | Product facts | Available colors | jsonb | conditional | Operator / supplier / reviewer | yes | no | yes if variants | yes | K07, Woo draft, catalog | Required for color variants. |
| `size_options_json` | Size options | Product facts | Available sizes | jsonb | conditional | Operator / supplier / reviewer | yes | no | yes if variants | yes | K07, Woo draft, catalog | Required for size variants. |
| `package_includes_json` | Package includes | Product facts | Package contents | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | Content, Woo draft | Do not fabricate accessories. |
| `certifications_json` | Certifications | Compliance / facts | Certification claims | jsonb | conditional | Operator / supplier / reviewer | structure only | no | yes | yes | Compliance, publish review | AI cannot confirm certifications. |
| `warranty_note_en` | Warranty note | Product facts | Warranty information in English | text | optional | Operator / reviewer | yes from source | no | yes if present | yes | Content, Woo draft | Must reflect approved warranty facts. |
| `safety_note_en` | Safety note | Compliance / facts | Safety notes in English | text | conditional | Operator / reviewer | yes from source | no | yes | yes | Content, risk review | Required when safety context exists. |
| `care_instructions_en` | Care instructions | Product facts | Care or maintenance instructions | text | conditional | Operator / supplier / reviewer | yes from source | no | yes | yes | Content, Woo draft | Should not invent maintenance rules. |
| `country_of_origin` | Country of origin | Product facts | Origin country | text | conditional | Operator / supplier / reviewer | no | no | yes | yes | Catalog, compliance, Woo draft | Do not infer from brand or manufacturer. |

## 8. SEO / feed / catalog

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `primary_keyword` | Primary keyword | SEO / keywords | Main approved keyword | text | required_before_content_generation | Reviewer / operator | yes | no | yes | yes | K15, content, P-series | Summary cache of approved keyword. |
| `secondary_keywords_json` | Secondary keywords | SEO / keywords | Approved secondary keywords | jsonb | required_before_content_generation | Reviewer / operator | yes | no | yes | yes | K15, content, P-series | Also normalized in keyword records later. |
| `long_tail_keywords_json` | Long-tail keywords | SEO / keywords | Approved long-tail keywords | jsonb | optional | Reviewer / operator | yes | no | yes | yes | K15, content | Candidate until reviewed. |
| `risk_keywords_json` | Risk keywords | SEO / risk | Risk keyword summary | jsonb | conditional | Reviewer / operator | yes | no | yes | yes | K20, content, publish review | Confirmed risk terms should be normalized later. |
| `seo_title_en` | SEO title | SEO / feed | English SEO title | text | required_before_woo_draft | Reviewer / operator | yes | no | yes | yes | Woo draft, P-series | Must not include unsupported claims. |
| `seo_description_en` | SEO description | SEO / feed | English SEO description | text | required_before_woo_draft | Reviewer / operator | yes | no | yes | yes | Woo draft, P-series | Draft until reviewed. |
| `slug` | Slug | SEO / feed | URL-safe slug | text | conditional | System / operator | yes | no | yes before publish | yes | Woo draft, catalog | Generated value still needs collision checks later. |
| `gtin` | GTIN | Feed / catalog | Global trade item number | text | conditional | Operator / supplier | no | no | yes | yes | Woo draft, feeds | Do not infer. |
| `upc` | UPC | Feed / catalog | UPC identifier | text | conditional | Operator / supplier | no | no | yes | yes | Woo draft, feeds | Do not infer. |
| `ean` | EAN | Feed / catalog | EAN identifier | text | conditional | Operator / supplier | no | no | yes | yes | Woo draft, feeds | Do not infer. |
| `mpn` | MPN | Feed / catalog | Manufacturer part number | text | conditional | Operator / supplier | no | no | yes | yes | Woo draft, feeds | Do not infer. |
| `asin_reference` | ASIN reference | Feed / catalog | Amazon reference identifier | text | optional | Operator / reviewer | no | no | yes if used | yes | Research, catalog mapping | Reference only, not copied dynamic system. |
| `google_product_category` | Google category | Feed / catalog | Google product category value | text | conditional | Reviewer / operator | yes | no | yes when channel uses Google Merchant/Product Feed | yes | Feed | Required when the target channel includes Google Merchant/Product Feed; not required for every basic Woo draft. |
| `merchant_product_type` | Merchant product type | Feed / catalog | Merchant-defined product type | text | conditional | Reviewer / operator | yes | no | yes when used | yes | Woo draft, feeds | Required before Woo draft only when Woo/catalog draft requires merchant category mapping; otherwise recommended before feed/catalog usage. |
| `category_hint` | Category hint | Feed / catalog | Draft category suggestion | text | required_before_category | AI draft / operator | yes | no | yes before approved use | yes | Category, K12 | Hint is not an approved category. |
| `category_path` | Category path | Feed / catalog | Approved category path | text/jsonb | required_before_woo_draft | Reviewer / operator | yes | no | yes | yes | Woo draft, P-series | `category_path` or approved category is required before Woo draft. |
| `category_confidence` | Category confidence | Feed / catalog | Confidence for category suggestion | decimal/jsonb | optional | AI draft / reviewer | yes | no | yes if used | no, except reviewer notes | K12, category review | Advisory only. |
| `target_market` | Target market | Readiness context | Market for keyword/unit/feed readiness | text | required_before_keyword_research | Operator / default market config | yes | no | yes | yes | K09, K15, K19 | Readiness/request context, not a required products-table column in K08A; product creation must not be blocked because it is missing. |

Target market resolution rules:

- Keyword research must be blocked if no `target_market` or approved default market can be resolved.
- Resolution priority:
  1. Explicit keyword research request payload.
  2. Product/workspace default market setting.
  3. Owner-approved fallback default.
  4. Future `k_product_knowledge_research_runs.target_market`.
- K09 uses `target_market` or `display_market` for unit display decisions, but K08A does not implement runtime storage.

## 9. Media / visual

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `main_image_url` | Main image URL | Media / visual | Main image pointer | text | conditional | Operator / media reviewer | no | no | yes | yes | K07, media work, Woo draft | Pointer only; no live storage integration in K08A. |
| `gallery_image_urls_json` | Gallery image URLs | Media / visual | Gallery image pointers | jsonb | optional | Operator / media reviewer | no | no | yes if used | yes | K07, media work, Woo draft | Must not contain secrets or signed URLs by design. |
| `video_urls_json` | Video URLs | Media / visual | Product video pointers | jsonb | optional | Operator / media reviewer | no | no | yes if used | yes | K07, media work | Optional. |
| `selected_image_path` | Selected image path | Media / visual | Reviewed selected image path | text | required_before_media_work | Operator / media reviewer | yes as suggestion | no | yes | yes | K07, K12, media work | Selection must be human-reviewed. |
| `visual_profile_path` | Visual profile path | Media / visual | Visual profile reference | text | conditional | Operator / media reviewer | yes as suggestion | no | yes | yes | Media work, future image generation | Pointer only. |
| `image_asset_status` | Image asset status | Media / visual | Image readiness lifecycle | enum/text | required_before_woo_draft | Media reviewer / operator | yes | no | yes | yes | K07, readiness, Woo draft | Must not be `blocked` for Woo draft. |
| `media_notes_json` | Media notes | Media / visual | Notes for image/video/visual review | jsonb | optional | Operator / media reviewer | yes | no | yes if used | yes | Media work, K12 | Can include non-secret review notes. |

## 10. AI / review

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deepseek_structured_output_json` | DeepSeek structured output | AI / review | Future structured AI draft payload | jsonb | optional | AI draft / mock adapter | yes | yes, draft only | yes before canonical use | no direct canonical edit | K10, K12 | K08A does not call live DeepSeek. |
| `ai_confidence_scores_json` | AI confidence scores | AI / review | Confidence by field or section | jsonb | optional | AI draft / mock adapter | yes | yes, draft only | yes if used | no, reviewer may annotate elsewhere | K12 | Advisory only. |
| `ai_warnings_json` | AI warnings | AI / review | AI warnings, missing facts, uncertainty | jsonb | optional | AI draft / mock adapter | yes | yes, draft only | yes | no, reviewer may resolve | K12, readiness | Warnings cannot be hidden during review. |
| `reviewed_by_user_id` | Reviewed by | AI / review | Last reviewer identity | UUID | conditional | System / reviewer | no | no, system only | no | no | K12, K21, publish review | Required before approved state. |
| `reviewed_at` | Reviewed at | AI / review | Review timestamp | timestamptz | conditional | System | no | no, system only | no | no | K12, K21, publish review | Required before approved state. |
| `manual_notes` | Manual notes | AI / review | Operator or reviewer notes | text | optional | Operator / reviewer | no | no | yes if decision notes | yes | K07, K12 | Human notes are not AI draft. |
| `field_diff_json` | Field diff | AI / review | AI draft vs canonical differences | jsonb | conditional | System / reviewer | no | no, system only | yes | no direct edit except review tooling | K12, K21 | Operator can accept, edit, or reject diffs later. |

## 11. Dynamic attributes

| Field key | Display label | Category | Purpose | Data type | Required level | Source of truth | AI can suggest? | AI can auto-write? | Human review required? | Editable by operator? | Used by downstream | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `attribute_key` | Attribute key | Dynamic attributes | Attribute identifier | text | conditional | Operator / reviewer / product-type rules | yes | no | yes | yes | K07, category, Woo draft | Required for each dynamic attribute row. |
| `attribute_value_text` | Attribute text value | Dynamic attributes | Text attribute value | text | conditional | Operator / reviewer | yes from source | no | yes if used | yes | K07, category, P-series | At least one value field should exist. |
| `attribute_value_json` | Attribute JSON value | Dynamic attributes | Structured attribute value | jsonb | conditional | Operator / reviewer | yes from source | no | yes if used | yes | K07, K09, P-series | Used for complex values or arrays. |
| `attribute_unit` | Attribute unit | Dynamic attributes | Unit for attribute value | text | conditional | Operator / reviewer | structure only | no | yes if unit matters | yes | K09, Woo draft | Must be explicit if unit-bearing. |
| `attribute_group` | Attribute group | Dynamic attributes | Attribute grouping such as marketplace/category/B2B | text | conditional | Operator / reviewer / product-type rules | yes | no | yes | yes | K07, catalog | Helps avoid ultra-wide core fields. |
| `requires_review` | Requires review | Dynamic attributes | Marks attribute as review-needed | boolean | conditional | System / reviewer | yes | no, system/reviewer only | yes when true | yes by reviewer | K12, readiness | Attribute review can block downstream gates. |
