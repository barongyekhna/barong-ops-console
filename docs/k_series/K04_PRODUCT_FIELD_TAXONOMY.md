# K04 Product Field Taxonomy

Status: K04 field taxonomy draft, pending owner review.

Date: 2026-06-11.

## 1. 字段设计原则

- English canonical fields are the primary product record.
- Raw input keeps the original operator language.
- AI output is draft data and must not silently overwrite human-confirmed fields.
- Product facts must not be invented by AI.
- K should support input in any language; future DeepSeek V4 Pro can translate, normalize, and structure it into English canonical data.
- The design may reference Amazon listing concepts, but it does not copy Amazon's dynamic field system.
- Core fields are standardized in the product table.
- Category-specific and marketplace-specific fields go into `k_product_knowledge_attributes`.

## 2. 必填字段

Readiness columns use these meanings:

- Product creation: required when the product record is first created.
- Keyword research: required before keyword research can run.
- WooCommerce draft: required before a future WooCommerce draft can be generated.
- Publish: required before a future publish-review gate can pass.

### A. system / identity

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `id` | Stable product row identity | required | required | required | required | system | no | yes, system only |
| `workspace_key` | Adapter-pending workspace boundary | required | required | required | required | system / owner config | no | yes, system only |
| `business_context` | Adapter-pending business context | required | required | required | required | system / owner config | no | yes, system only |
| `scope_mode` | Marks `adapter_pending` scope behavior | required | required | required | required | system / owner config | no | yes, system only |
| `product_key` | Human-stable K product identifier | required | required | required | required | operator / owner | yes | no |
| `product_status` | Lifecycle state | required | required | required | required | operator / reviewer | yes | no |
| `canonical_language` | Canonical record language, default `en` | required | required | required | required | system / owner config | no | yes, system only |
| `created_at` | Creation timestamp | required | required | required | required | system | no | yes, system only |
| `updated_at` | Update timestamp | required | required | required | required | system | no | yes, system only |

### B. source

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `source_system` | Source channel such as manual/imported/future API | required | required | required | required | operator / system | yes | no |
| `source_record_id` | External source row or record ID | optional | optional | recommended | recommended | operator / system | no | no |
| `raw_input_text` | Original product input | required | required | required | required | operator | no | no |
| `raw_input_language` | Original input language | required | required | required | required | operator / reviewer | yes | no |

### C. core product info

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `product_name_en` | Canonical English product name | optional | required | required | required | operator / reviewer | yes | no |
| `brand_name` | Brand identity | optional | recommended | required if branded | required if branded | operator / reviewer | yes | no |
| `manufacturer` | Manufacturer identity | optional | optional | recommended | recommended | operator / reviewer | yes | no |
| `product_type` | Normalized product type | optional | required | required | required | operator / reviewer | yes | no |
| `short_description_en` | Short English product summary | optional | recommended | required | required | operator / reviewer | yes | no |
| `primary_use_case_en` | Primary use scenario | optional | required | recommended | required | operator / reviewer | yes | no |
| `target_customer_en` | Target buyer/user | optional | recommended | recommended | required | operator / reviewer | yes | no |

### D. variant basics

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `sku` | Sellable SKU identifier | optional | optional | required | required | operator / reviewer | no | no |
| `parent_product_id` | Parent row for variants | optional | optional | required for variants | required for variants | operator / reviewer | yes | no |
| `variant_group_key` | Groups variants together | optional | optional | required for variants | required for variants | operator / reviewer | yes | no |
| `color_options_json` | Available colors | optional | recommended for variants | required if color variant | required if color variant | operator / reviewer | yes | no |
| `size_options_json` | Available sizes | optional | recommended for variants | required if size variant | required if size variant | operator / reviewer | yes | no |

### E. dimensions / weight minimum

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `dimensions_json` | Product dimensions with original and normalized units | optional | recommended | required when shipping/display needs dimensions | required when applicable | operator / reviewer | structure only | no |
| `weight_json` | Product weight with original and normalized units | optional | recommended | required when shipping/display needs weight | required when applicable | operator / reviewer | structure only | no |
| `package_dimensions_json` | Packaged dimensions | optional | optional | recommended | required when shipping requires it | operator / reviewer | structure only | no |
| `package_weight_json` | Packaged weight | optional | optional | recommended | required when shipping requires it | operator / reviewer | structure only | no |

### F. commerce minimum

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `regular_price` | Base selling price | optional | optional | required | required | operator / owner | no | no |
| `sale_price` | Sale price if any | optional | optional | optional | optional | operator / owner | no | no |
| `price_currency` | Currency for prices | optional | optional | required | required | operator / owner | no | no |
| `stock_status` | Stock status | optional | optional | required | required | operator / owner | no | no |
| `inventory_quantity` | Stock quantity | optional | optional | required if managed | required if managed | operator / owner | no | no |
| `manage_stock` | Whether inventory is tracked | optional | optional | required | required | operator / owner | no | no |

### G. review / status

| Field name | Purpose | Product creation | Keyword research | WooCommerce draft | Publish | Who can edit | AI can suggest? | AI can auto-write? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `review_status` | Human review state | required | required | required | required | reviewer / owner | yes | no |
| `reviewed_by_user_id` | Last reviewer | optional | required before approval | required before approval | required | reviewer / system | no | yes, system only |
| `reviewed_at` | Review timestamp | optional | required before approval | required before approval | required | system | no | yes, system only |
| `manual_notes` | Reviewer notes | optional | optional | recommended | recommended | operator / reviewer | no | no |
| `field_diff_json` | AI draft vs human-reviewed field differences | optional | recommended | recommended | recommended | system / reviewer | no | yes, system only |

## 3. 选填字段

Supplier fields:

- `manufacturer`
- supplier name as a future attribute
- supplier SKU as a future attribute
- `moq`
- `lead_time`
- `country_of_origin`
- supplier warranty notes as an attribute

Marketplace fields:

- `gtin`
- `upc`
- `ean`
- `mpn`
- `asin_reference`
- `google_product_category`
- `merchant_product_type`
- marketplace-specific attributes in `k_product_knowledge_attributes`

SEO fields:

- `primary_keyword`
- `secondary_keywords_json`
- `long_tail_keywords_json`
- `seo_title_en`
- `seo_description_en`
- `slug`
- `category_hint`
- `category_path`
- `category_confidence`

Media fields:

- `main_image_url`
- `gallery_image_urls_json`
- `video_urls_json`
- `selected_image_path`
- `visual_profile_path`
- `image_asset_status`
- `media_notes_json`

Compliance fields:

- `certifications_json`
- `safety_note_en`
- `care_instructions_en`
- `risk_keywords_json`
- risk terms in `k_product_knowledge_risk_terms`
- regulated-product attributes

B2B fields:

- `moq`
- `lead_time`
- packaging attributes
- bulk pricing attributes
- wholesale buyer notes
- industry/application attributes

Creative/ad fields:

- selling point refinements
- benefit bullets
- image generation notes
- visual profile references
- ad angle attributes
- creative constraints

Lifecycle fields:

- `product_status`
- `review_status`
- `image_asset_status`
- `stock_status`
- version history
- review item status

## 4. AI 生成字段

The following fields can be AI-generated as draft only until reviewed:

- normalized product name suggestion;
- feature bullets;
- benefit bullets;
- SEO title;
- SEO description;
- keyword suggestions;
- risk term suggestions;
- translated review payloads;
- selling point refinement;
- category hints;
- structured product facts from provided input only.

Rule: AI draft only until reviewed. AI must not silently overwrite canonical reviewed fields.

## 5. 人工审核字段

Fields that must be manually reviewed or manually overrideable:

- canonical `product_name_en`;
- price;
- SKU;
- product facts;
- dimensions;
- weight;
- claims;
- certifications;
- risk terms;
- category;
- keywords;
- media selection;
- `product_type`;
- `brand_name`;
- `country_of_origin`;
- WooCommerce feed identifiers.

Manual confirmation is required before these fields are used for publish-facing output.

## 6. 阶段 readiness

### `ready_for_keyword_research`

Affected fields:

- `product_name_en`
- `product_type`
- `raw_input_text`
- `raw_input_language`
- `primary_use_case_en`
- `target_customer_en`
- `review_status`

Meaning: the product has enough reviewed or reviewable identity/context to generate keyword candidates.

### `ready_for_category`

Affected fields:

- `product_name_en`
- `product_type`
- `brand_name`
- `materials_json`
- `primary_use_case_en`
- `target_customer_en`
- existing category hints or marketplace attributes

Meaning: the product has enough product-type and fact context to choose or recommend catalog categories.

### `ready_for_page_blueprint`

Affected fields:

- `product_name_en`
- `short_description_en`
- `long_description_en`
- `primary_use_case_en`
- `target_customer_en`
- reviewed keywords
- confirmed risk terms
- product facts

Meaning: the product can feed a future page-structure blueprint without relying on fabricated facts.

### `ready_for_content_generation`

Affected fields:

- canonical English fields
- reviewed product facts
- reviewed keywords
- confirmed risk terms
- claims and certifications review
- category path or category hint

Meaning: AI or template content generation may proceed using reviewed canonical inputs.

### `ready_for_media_work`

Affected fields:

- `product_name_en`
- `product_type`
- `selected_image_path`
- `visual_profile_path`
- `main_image_url`
- `gallery_image_urls_json`
- `media_notes_json`
- media asset review status

Meaning: image selection, visual profile work, or future image generation has enough product and visual context.

### `ready_for_woo_draft`

Affected fields:

- `sku`
- `product_name_en`
- `short_description_en`
- `long_description_en`
- `regular_price`
- `price_currency`
- `stock_status`
- `manage_stock`
- product dimensions/weight when needed
- media pointers
- category path or merchant product type
- reviewed keywords
- confirmed risk terms

Meaning: a future WooCommerce draft can be generated through K API and backend integration after the relevant future tasks.

### `ready_for_publish_review`

Affected fields:

- all WooCommerce draft fields;
- reviewed canonical English fields;
- reviewed product facts;
- reviewed pricing and SKU;
- confirmed claims, certifications, and risk terms;
- approved keywords;
- approved media selection;
- open review items resolved or explicitly accepted.

Meaning: the product can enter a future publish-review workflow. Formal approval still waits for C12.
