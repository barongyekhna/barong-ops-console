# K08 Product Field System

Status: K08A field-system draft, pending owner review.

Date: 2026-06-12.

## 1. K08A 目标

K08A 只深化 K Product Knowledge 的产品字段体系。

- K08A 不写 Python 代码。
- K08A 不写 frontend。
- K08A 不写 tests。
- K08A 不创建 migration。
- K08A 不修改已有 migration。
- K08A 不修改 backend runtime、frontend runtime、router、main.py、core config、core permissions、core auth/deps。
- K08A 不连接 live services，不读取 env，不运行 Docker、Alembic、Postgres、staging 或 production。
- K08A 是 K07 前端表单、K09 单位换算、K10 DeepSeek mock adapter、K12 英文 canonical 审核、K15 关键词调研、K20 风险词管理的统一字段基准。

K08A 的输出是字段体系和字段字典文档，不改变当前数据库结构和运行时行为。

## 2. 字段体系原则

- English canonical fields 是主记录。
- Raw input 保留原语言、原始上下文和操作者输入痕迹。
- AI 输出只能作为 draft。
- AI 不得编造产品事实。
- 人工确认字段优先级高于 AI draft。
- AI draft 不得静默覆盖人工确认字段。
- 支持任意语言输入。
- 支持后续 DeepSeek V4 Pro 英文化、结构化、翻译，但 K08A 不接 live DeepSeek。
- 参考 Amazon listing 思路，但不复制 Amazon 动态字段系统。
- 核心字段标准化，品类/市场字段进入 attributes。
- Product Knowledge 的长期 source of truth 是 Barong K 数据表族，不再是 Google Sheets。
- Google Sheets 不再作为 Product Knowledge 长期 source of truth。
- n8n 未来只能通过 Barong backend API 调用 K，不得直接写 Barong DB。
- 所有下游消费都应通过 future K API 读取 reviewed canonical fields、approved keywords、confirmed risk terms 和 reviewed media pointers。

## 3. 字段分层

### A. System / identity fields

Purpose: 保证 K 记录在 adapter-pending scope 下可唯一定位、可审计、可进入生命周期管理。

Representative fields:

- `id`
- `workspace_key`
- `business_context`
- `scope_mode`
- `product_key`
- `source_system`
- `source_record_id`
- `sku`
- `parent_product_id`
- `variant_group_key`
- `product_status`
- `review_status`
- `canonical_language`
- `created_by_user_id`
- `updated_by_user_id`
- `created_at`
- `updated_at`

Rules:

- `workspace_key`, `business_context`, and `scope_mode` keep K inside the K Scope Shim until formal C scope integration is approved.
- `product_key` is the stable human-facing K identifier.
- `sku` is a sellable identifier and must be reviewed before WooCommerce draft or publish-facing usage.
- Variant fields are optional until variant behavior is needed.

### B. Source / import fields

Purpose: 记录产品信息来自 manual input、future import、future API 或其他批准来源。

Representative fields:

- `source_system`
- `source_record_id`
- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`

Rules:

- Raw input is preserved even after canonical English fields are reviewed.
- Future imports must not make Google Sheets the long-term Product Knowledge source of truth.
- Source fields can support reconciliation, but they do not replace K canonical fields.

### C. Canonical English product fields

Purpose: 作为主产品记录，供审核、关键词、内容、媒体、WooCommerce draft 和未来 P 系列消费。

Representative fields:

- `product_name_en`
- `brand_name`
- `manufacturer`
- `product_type`
- `short_description_en`
- `long_description_en`
- `primary_use_case_en`
- `target_customer_en`

Rules:

- English canonical fields are the master record.
- AI may suggest values as draft, but human-reviewed canonical values win.
- Canonical fields must not contain unsupported claims or fabricated facts.

### D. Raw input fields

Purpose: 保存原语言输入和原始结构，支持人工复核、多语言检查和未来 DeepSeek V4 Pro 结构化。

Representative fields:

- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`

Rules:

- Raw input may be any language.
- Raw input is not automatically publishable content.
- Raw input can feed future mock/live adapter input, but K08A does not call a live provider.

### E. Commercial fields

Purpose: 支持价格、库存、采购、履约和 future WooCommerce draft 的基础商业数据。

Representative fields:

- `regular_price`
- `sale_price`
- `price_currency`
- `cost`
- `margin`
- `stock_status`
- `inventory_quantity`
- `manage_stock`
- `moq`
- `lead_time`
- `shipping_class`
- `tax_class`

Rules:

- AI must not invent price, stock, cost, tax, margin, lead time, MOQ, or shipping values.
- Prices and inventory must be human-reviewed before WooCommerce draft or publish review.
- Cost and margin are internal fields and must not be exposed to downstream publish-facing output unless explicitly approved in a later task.

### F. Dimensions / weight / unit fields

Purpose: 支持 K09 单位换算、market display、shipping data 和 future WooCommerce draft。

Representative fields:

- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`

Rules:

- Preserve original values and original units.
- Store normalized metric and imperial values with explicit unit labels.
- Include display market and conversion source where applicable.
- AI may structure provided values, but must not guess missing dimensions or weight.
- Reviewed unit payloads are the K09 baseline.

### G. Product facts / materials / package fields

Purpose: 记录产品事实、材料、尺寸选项、包装、认证、保养、安全和产地等不可编造信息。

Representative fields:

- `materials_json`
- `color_options_json`
- `size_options_json`
- `package_includes_json`
- `certifications_json`
- `warranty_note_en`
- `safety_note_en`
- `care_instructions_en`
- `country_of_origin`

Rules:

- Product facts must come from operator input, supplier data, approved import data, or reviewed source material.
- Certifications and country of origin require human review.
- AI may normalize wording or structure from provided facts only.

### H. Compliance / claims / risk fields

Purpose: 支持 claims 审核、risk term 管理、平台政策风险识别和 publish review。

Representative fields:

- `certifications_json`
- `safety_note_en`
- `care_instructions_en`
- `risk_keywords_json`
- future normalized risk-term records such as `term_en`, `term_zh`, `risk_type`, `risk_reason`, `suggested_action`, and `status`

Rules:

- AI must not confirm claims, certifications, or compliance status.
- Risk suggestions are candidates until a human confirms or removes them.
- Confirmed risk terms must be visible to future page generation, WooCommerce draft and ad-material flows through the K API.

### I. SEO / feed / catalog fields

Purpose: 支持关键词、SEO、marketplace feed、catalog category 和 future page/content generation。

Representative fields:

- `primary_keyword`
- `secondary_keywords_json`
- `long_tail_keywords_json`
- `risk_keywords_json`
- `seo_title_en`
- `seo_description_en`
- `slug`
- `gtin`
- `upc`
- `ean`
- `mpn`
- `asin_reference`
- `google_product_category`
- `merchant_product_type`
- `category_hint`
- `category_path`
- `category_confidence`

Rules:

- Keywords remain manually editable.
- AI/provider keyword output is candidate or draft until reviewed.
- Feed identifiers require operator/reviewer confirmation before downstream usage.
- Category hints may be AI suggested, but approved categories must be human-reviewed.

### J. Media / visual fields

Purpose: 记录主图、图库、视频、已选图片、视觉 profile 和 future media workflow 状态。

Representative fields:

- `main_image_url`
- `gallery_image_urls_json`
- `video_urls_json`
- `selected_image_path`
- `visual_profile_path`
- `image_asset_status`
- `media_notes_json`

Rules:

- K08A only defines media pointers and readiness expectations.
- K08A does not connect MinIO, Filebrowser, image generation, WooCommerce media upload, or any live storage provider.
- Media selection must be reviewed before publish-facing usage.

### K. AI draft / review fields

Purpose: 保存 future DeepSeek structured output、AI confidence/warnings、人工审核状态和 field diff。

Representative fields:

- `deepseek_structured_output_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- `reviewed_by_user_id`
- `reviewed_at`
- `manual_notes`
- `field_diff_json`

Rules:

- AI draft only until reviewed.
- `field_diff_json` records AI draft vs canonical field differences.
- Operator can accept, edit, or reject draft values.
- Reviewed values must record reviewer identity and review time where practical.

### L. Keywords / risk terms fields

Purpose: 支持 K15/K19 keyword workflow 和 K20 risk term workflow。

Representative fields:

- Product summary fields: `primary_keyword`, `secondary_keywords_json`, `long_tail_keywords_json`, `risk_keywords_json`
- Future normalized keyword records: `keyword_text`, `keyword_type`, `language_code`, `market`, `search_intent`, `source`, `status`, `reason`
- Future normalized risk-term records: `term_en`, `term_zh`, `risk_type`, `risk_reason`, `suggested_action`, `source`, `status`

Rules:

- Main keywords, secondary keywords, long-tail keywords and risk keywords are manually editable.
- Provider-originated keyword and risk-term output remains candidate data until reviewed.
- K20 risk terms write back to the K risk field model, not to P workflow JSON.

### M. Readiness / lifecycle fields

Purpose: 控制下游流程是否可以进入 keyword research、category、page blueprint、content generation、media work、WooCommerce draft 和 publish review。

Representative fields:

- `product_status`
- `review_status`
- `image_asset_status`
- future gate status payloads such as `ready_for_keyword_research`, `ready_for_category`, `ready_for_page_blueprint`, `ready_for_content_generation`, `ready_for_media_work`, `ready_for_woo_draft`, and `ready_for_publish_review`

Rules:

- AI cannot bypass readiness gates.
- Blocked gates must provide errors and warnings.
- Operators can fix fields and recheck gates in a future implementation.
- K08A defines gates only and does not implement runtime checks.

### N. Dynamic attributes

Purpose: 承载品类、市场、B2B、marketplace-specific 和 Amazon-like product type 扩展字段。

Representative fields:

- `attribute_key`
- `attribute_value_text`
- `attribute_value_json`
- `attribute_unit`
- `attribute_group`
- `requires_review`

Rules:

- Core product fields remain standardized.
- Category-specific and marketplace-specific fields go into attributes.
- At least one value field should be present.
- Repeated attributes require future explicit product-type rules.

## 4. K08 与其他 K 任务关系

- K07 前端表单必须基于 K08 字段体系。
- K07 如果现在做，只能 hidden-by-default，不挂正式菜单，不接正式 scope，不接 live provider。
- K09 单位换算必须基于 K08 dimensions / weight 字段。
- K10 DeepSeek mock adapter 必须输出 K08 canonical field payload。
- K12 审核界面必须围绕 K08 AI draft / canonical field diff。
- K15 关键词调研按钮必须读取 K08 readiness。
- K20 风险词必须写回 K08 risk field model。
- K21 未来接 operation logs 时只能使用既有 operation log contract，不改 `operation_logs` 表结构。
- K28/P 系列未来只能通过 K API 消费 K08 字段。
- n8n 未来不得直接写 Barong DB。
- K08A 不读取、不修改 P-series workflow JSON。
