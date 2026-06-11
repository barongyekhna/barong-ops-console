# K04 Product Knowledge Schema Design

Status: K04 schema design draft, pending owner review.

Date: 2026-06-11.

## 1. K04 目标

K04 only designs the database schema draft for the K series Product Knowledge table family.

- K04 only designs K database schema.
- K04 does not create migrations.
- K04 does not create tables.
- K04 does not modify backend runtime.
- K04 does not modify frontend runtime.
- K04 does not run Docker, Alembic, Postgres, staging, or production scripts.
- K04 is the review material required before a future K05 migration.

## 2. K 系列定位

- K series = Knowledge / 产品知识库 / 白苏婉 2.0.
- K series is not C07.
- K series is not P series.
- K series replaces Google Sheets `Product_Knowledge` as the long-term source of truth.
- K series will later provide structured product knowledge to P series, page generation, WooCommerce drafts, image generation, ad material generation, and related modules.
- n8n may later read from or write to K series only through Barong backend API.
- n8n must not write directly to the Barong database.

## 3. scope-adapter-pending 设计

The formal scope system is not complete yet. K series can proceed with functional design while staying `scope-adapter-pending`.

K series uses a K Scope Shim with these temporary fields:

| Field | Temporary value |
| --- | --- |
| `workspace_key` | `default_independent_store` |
| `business_context` | `independent_store` |
| `scope_mode` | `adapter_pending` |

Design rules:

- K series keeps the adapter pending until the formal C adapters are ready.
- Future formal adapter connection waits for C07, C08, C13, and C18.
- K04 does not design the formal scope system.
- K04 does not modify `users`, `roles`, `permissions`, `organizations`, or any core scope structure.
- K tables keep the temporary shim fields so K05 can create isolated tables without depending on not-yet-complete formal scope tables.

## 4. 数据库隔离原则

- Only add the K table family.
- K table names use the prefix `k_product_knowledge_`.
- Do not alter core tables.
- Do not change the `operation_logs` table structure.
- Do not change `users`, `roles`, `permissions`, `organizations`, or scope tables.
- Future K05 migration may only create K table-family tables.
- Every K table must include `created_at` and `updated_at`.
- Tables that need manual traceability should keep `created_by_user_id` and `updated_by_user_id` when practical.
- While formal scope is incomplete, K tables use `workspace_key`, `business_context`, and `scope_mode` as adapter-pending transition fields.

## 5. 推荐 K 表族总览

### 5.1 `k_product_knowledge_products`

- Purpose: canonical product master record for the K Product Knowledge database.
- Core columns: identity shim fields, source fields, canonical English fields, commercial fields, product facts, SEO/catalog fields, media pointers, AI draft payloads, review fields, audit timestamps.
- Nullable / required recommendation: `id`, `workspace_key`, `business_context`, `scope_mode`, `product_key`, `product_status`, `canonical_language`, `review_status`, `created_at`, and `updated_at` are required. Source, commerce, facts, SEO, media, AI, and review details may be nullable until the related readiness gate.
- Indexes: `(workspace_key, business_context, product_key)`, `(workspace_key, business_context, sku)`, `product_status`, `review_status`, `parent_product_id`, `variant_group_key`, `created_at`, `updated_at`.
- Unique constraints: unique `(workspace_key, business_context, product_key)`; partial unique `(workspace_key, business_context, sku)` where `sku is not null`.
- Relationship to other K tables: parent table for attributes, translations, keywords, risk terms, research runs, AI events, versions, media assets, and review items.
- Future C dependency if any: formal scope adapter after C18; formal module/permission integration after C07/C08/C13.
- Why isolated from core C tables: Product Knowledge is a K-owned domain and must not require core scope, user, organization, or operation log schema changes.

### 5.2 `k_product_knowledge_attributes`

- Purpose: dynamic attribute storage for Amazon-like product type fields and marketplace-specific fields.
- Core columns: `id`, `product_id`, `attribute_key`, text/json value fields, unit, group, source, confidence, review fields, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `attribute_key`, `created_at`, and `updated_at` are required. Value fields are nullable individually, but at least one of `attribute_value_text` or `attribute_value_json` should be present.
- Indexes: `product_id`, `(product_id, attribute_key)`, `attribute_group`, `source`, `requires_review`, `created_at`.
- Unique constraints: recommended unique `(product_id, attribute_key, attribute_group)` when attributes are single-valued; allow repeated keys only when future product-type rules explicitly require arrays.
- Relationship to other K tables: child of products.
- Future C dependency if any: none for storage; formal review or permission behavior waits for C12/C07/C13.
- Why isolated from core C tables: dynamic product attributes are K domain data and should not expand core product, user, or organization schemas.

### 5.3 `k_product_knowledge_translations`

- Purpose: multilingual review/display payloads derived from the English canonical product record.
- Core columns: `id`, `product_id`, `language_code`, `translation_type`, source hash, translated payload, provider metadata, review fields, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `language_code`, `translation_type`, `source_text_hash`, `review_status`, `created_at`, and `updated_at` are required. Provider fields are nullable for manually entered or mock data.
- Indexes: `product_id`, `(product_id, language_code)`, `(language_code, translation_type)`, `review_status`, `created_at`.
- Unique constraints: recommended unique `(product_id, language_code, translation_type, source_text_hash)`.
- Relationship to other K tables: child of products; may be referenced by versions or review items through payload snapshots.
- Future C dependency if any: live DeepSeek waits for C14/C09 and owner approval.
- Why isolated from core C tables: translations are product-review support data and do not belong in core user, permission, organization, or operation log tables.

### 5.4 `k_product_knowledge_keywords`

- Purpose: manually editable keyword candidates and approved keywords for product research and downstream generation.
- Core columns: `id`, `product_id`, keyword text, keyword type, language, market, intent, source, status, confidence, reason, review fields, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `keyword_text`, `keyword_type`, `language_code`, `status`, `created_at`, and `updated_at` are required. Market, confidence, reason, and review fields are nullable until research/review is complete.
- Indexes: `product_id`, `(product_id, keyword_type)`, `(product_id, status)`, `(language_code, market)`, `created_at`.
- Unique constraints: recommended unique `(product_id, lower(keyword_text), keyword_type, language_code, coalesce(market, ''))`.
- Relationship to other K tables: child of products; selected keyword IDs may be stored by research runs.
- Future C dependency if any: live SERP/OpenAI/Claude provider execution waits for C14/C09 and owner approval.
- Why isolated from core C tables: keyword lifecycle is K-owned product knowledge, not a core platform concern.

### 5.5 `k_product_knowledge_risk_terms`

- Purpose: policy, compliance, platform, and claim-risk terms connected to a product.
- Core columns: `id`, `product_id`, English/Chinese terms, risk type, reason, suggested action, source, status, confirmation fields, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `term_en`, `risk_type`, `status`, `created_at`, and `updated_at` are required. `term_zh`, reason, and suggested action are nullable but recommended for review.
- Indexes: `product_id`, `(product_id, risk_type)`, `status`, `created_at`.
- Unique constraints: recommended unique `(product_id, lower(term_en), risk_type)`.
- Relationship to other K tables: child of products; may be linked to keywords by semantic match in future runtime without a hard schema dependency.
- Future C dependency if any: formal approval gates wait for C12; live provider suggestions wait for C14/C09.
- Why isolated from core C tables: risk terms are product content review data and should not alter core policy or audit schemas.

### 5.6 `k_product_knowledge_research_runs`

- Purpose: records keyword research button runs and provider pipeline summaries.
- Core columns: `id`, `product_id`, run type, status, requester, market/language, seed keywords, provider summaries, selected keyword IDs, errors, start/finish times, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `run_type`, `status`, `target_market`, `target_language`, `created_at`, and `updated_at` are required. Provider summaries and errors are nullable depending on status.
- Indexes: `product_id`, `status`, `(target_market, target_language)`, `requested_by_user_id`, `started_at`, `created_at`.
- Unique constraints: no broad uniqueness; optional idempotency key may be added in a future runtime design.
- Relationship to other K tables: child of products; AI events may reference a research run; selected keyword IDs refer to K keyword records.
- Future C dependency if any: K15 skeleton can be designed first; live K16/K17/K18 providers wait for C14/C09 and owner approval.
- Why isolated from core C tables: research execution state belongs to K and must not change core job or provider tables during K04.

### 5.7 `k_product_knowledge_ai_events`

- Purpose: append-style event log for DeepSeek, ChatGPT, Claude, SERP, and related provider calls or mock events.
- Core columns: `id`, `product_id`, nullable `research_run_id`, event/provider metadata, prompt version, input hash, output summaries/payloads, status, error fields, token/cost estimates, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `event_type`, `provider`, `status`, `created_at`, and `updated_at` are required. `research_run_id`, provider model, prompt version, payloads, errors, token estimates, and cost estimates are nullable.
- Indexes: `product_id`, `research_run_id`, `provider`, `event_type`, `status`, `created_at`.
- Unique constraints: none by default; provider events are append-only.
- Relationship to other K tables: child of products; optional child of research runs.
- Future C dependency if any: live provider execution waits for C14/C09 and owner approval.
- Why isolated from core C tables: AI/provider event details are K domain evidence and must not store secrets or alter core audit tables.

### 5.8 `k_product_knowledge_versions`

- Purpose: product data version history for manual edits, AI draft changes, keyword confirmation, and risk term confirmation.
- Core columns: `id`, `product_id`, `version_number`, `change_type`, actor/source fields, before/after/diff JSON, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `version_number`, `change_type`, `change_source`, `created_at`, and `updated_at` are required. Actor and JSON payloads may be nullable for system events but should be present for meaningful changes.
- Indexes: `product_id`, `(product_id, version_number)`, `change_type`, `changed_by_user_id`, `created_at`.
- Unique constraints: unique `(product_id, version_number)`.
- Relationship to other K tables: child of products; may snapshot changes from other K child tables in JSON.
- Future C dependency if any: formal audit page display waits for C17; formal approval waits for C12.
- Why isolated from core C tables: K can keep product-domain version evidence without modifying `operation_logs`.

### 5.9 `k_product_knowledge_media_assets`

- Purpose: references to product images, videos, visual profiles, and future image-generation assets.
- Core columns: `id`, `product_id`, asset type/role, storage provider, object key, URL placeholder, file metadata, source, status, review status, metadata JSON, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `asset_type`, `asset_role`, `status`, `review_status`, `created_at`, and `updated_at` are required. Storage fields are nullable while no live MinIO/Filebrowser integration exists.
- Indexes: `product_id`, `(product_id, asset_role)`, `asset_type`, `status`, `review_status`, `created_at`.
- Unique constraints: optional unique `(product_id, asset_role, object_key)` where `object_key is not null`.
- Relationship to other K tables: child of products; media status may feed review items or versions.
- Future C dependency if any: live MinIO/Filebrowser and image-generation workflows wait for future K/P/C approvals.
- Why isolated from core C tables: media references are K product knowledge assets and should not require storage runtime integration during schema design.

### 5.10 `k_product_knowledge_review_items`

- Purpose: placeholder review tasks for K product data, keywords, risks, media, and future approval surfaces.
- Core columns: `id`, `product_id`, review type, status, severity, title, description, proposed changes, decision, actor fields, review timestamp, timestamps.
- Nullable / required recommendation: `id`, `product_id`, `review_type`, `status`, `severity`, `title`, `created_at`, and `updated_at` are required. Assignment, decision, and reviewed fields are nullable until review.
- Indexes: `product_id`, `review_type`, `status`, `severity`, `assigned_to_user_id`, `created_at`.
- Unique constraints: none by default; future runtime may add dedupe keys for repeated review signals.
- Relationship to other K tables: child of products; can reference proposed changes for any K table through JSON.
- Future C dependency if any: formal approval gates wait for C12; permission/menu integration waits for C07/C13.
- Why isolated from core C tables: K22 review placeholders must not implement or alter core approval systems.

## 6. `k_product_knowledge_products` 草案

### A. identity fields

Recommended required fields:

- `id UUID`
- `workspace_key`
- `business_context`
- `scope_mode`
- `product_key`
- `product_status`
- `canonical_language`
- `review_status`
- `created_at`
- `updated_at`

Recommended nullable fields:

- `source_system`
- `source_record_id`
- `sku`
- `parent_product_id`
- `variant_group_key`
- `created_by_user_id`
- `updated_by_user_id`

Notes:

- `canonical_language` should default to `en`.
- `scope_mode` should default to `adapter_pending` while formal scope is incomplete.
- `review_status` is required and should default to `draft`.
- `parent_product_id` references another K product row for variants only.

### B. canonical English product fields

- `product_name_en`
- `brand_name`
- `manufacturer`
- `product_type`
- `short_description_en`
- `long_description_en`
- `primary_use_case_en`
- `target_customer_en`

Recommendation:

- `product_name_en` and `product_type` should be required before downstream generation.
- Descriptions and audience fields can start nullable and become required by readiness gates.
- AI may suggest these fields, but reviewed canonical values must not be silently overwritten.

### C. commercial fields

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

Recommendation:

- `price_currency`, `regular_price`, and `stock_status` should be required before WooCommerce draft.
- `cost` and `margin` are internal commercial fields and should remain nullable unless the owner requires them.
- AI may not invent price, stock, cost, margin, or tax values.

### D. product fact fields

- `materials_json`
- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`
- `color_options_json`
- `size_options_json`
- `package_includes_json`
- `certifications_json`
- `warranty_note_en`
- `safety_note_en`
- `care_instructions_en`
- `country_of_origin`

Recommendation:

- Product facts must come from operator input, supplier data, or approved source data.
- AI may normalize wording and structure but must not fabricate missing product facts.
- Dimensions and weight should follow the unit conversion model in `K04_UNIT_AND_MARKET_CONVERSION_MODEL.md`.

### E. SEO / feed / catalog fields

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

Recommendation:

- Keywords should also be normalized into `k_product_knowledge_keywords`.
- Risk keywords should also be normalized into `k_product_knowledge_risk_terms` when they represent policy or claim risks.
- Feed identifiers are nullable but should be protected from unreviewed AI overwrite.

### F. media fields

- `main_image_url`
- `gallery_image_urls_json`
- `video_urls_json`
- `selected_image_path`
- `visual_profile_path`
- `image_asset_status`
- `media_notes_json`

Recommendation:

- These fields are placeholders and pointers, not live storage integration.
- Canonical media asset records should live in `k_product_knowledge_media_assets`.
- K04 does not connect MinIO, Filebrowser, image generation workflows, or other live media systems.

### G. AI and review fields

- `raw_input_text`
- `raw_input_language`
- `deepseek_structured_output_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- `review_status`
- `reviewed_by_user_id`
- `reviewed_at`
- `manual_notes`
- `field_diff_json`

Recommendation:

- Raw input preserves the original language and operator context.
- DeepSeek structured output is future draft data only.
- `review_status` is required, should default to `draft`, and should track the draft/review lifecycle.
- Recommended `review_status` values: `draft`, `ai_structured`, `needs_review`, `reviewed`, `approved`, `blocked`, `archived`.
- `field_diff_json` should capture differences between AI draft and human-reviewed canonical fields.
- K04 does not connect live DeepSeek or read provider secrets.

## 7. `k_product_knowledge_attributes` 草案

Required field set:

- `id`
- `product_id`
- `attribute_key`
- `created_at`
- `updated_at`

Nullable field set:

- `attribute_value_text`
- `attribute_value_json`
- `attribute_unit`
- `attribute_group`
- `source`
- `confidence`
- `requires_review`
- `reviewed_by_user_id`
- `reviewed_at`

Design recommendation:

- Use this table for product-type attributes, marketplace-specific attributes, and B2B/category extensions.
- Do not create a permanently ultra-wide product table for every possible category field.
- Core product fields stay standardized in `k_product_knowledge_products`.
- Category/marketplace fields go into attributes so K can support future Amazon-like product types without changing the core table for every marketplace.
- `attribute_value_text` and `attribute_value_json` are nullable individually, but at least one must exist.
- K05 may use check constraint: `attribute_value_text IS NOT NULL OR attribute_value_json IS NOT NULL`.
- Do not make both value fields NOT NULL.
- Use an at-least-one-value check constraint in K05 if supported.

## 8. `k_product_knowledge_translations` 草案

Required field set:

- `id`
- `product_id`
- `language_code`
- `translation_type`
- `source_text_hash`
- `translated_payload_json`
- `provider`
- `provider_model`
- `review_status`
- `reviewed_by_user_id`
- `reviewed_at`
- `created_at`
- `updated_at`

Design rules:

- English canonical data is the master product record.
- Other languages are review/display aids, not the source of truth.
- The multilingual review interface must not use ordinary machine translation as the final translation source.
- Future DeepSeek V4 Pro is expected to handle translation, English normalization, and structured payload generation.
- K04 does not connect live DeepSeek, read provider keys, or call any live provider.

## 9. `k_product_knowledge_keywords` 草案

Required field set:

- `id`
- `product_id`
- `keyword_text`
- `keyword_type`: `primary` / `secondary` / `long_tail` / `b2b` / `negative` / `risk`
- `language_code`
- `market`
- `search_intent`
- `source`: `manual` / `serp` / `chatgpt` / `claude` / `imported` / `unknown`
- `status`: `candidate` / `approved` / `rejected` / `removed`
- `confidence`
- `reason`
- `created_at`
- `updated_at`
- `reviewed_by_user_id`
- `reviewed_at`

Design rules:

- Main keywords, secondary keywords, long-tail keywords, B2B keywords, negative keywords, and risk keywords must be manually editable.
- AI/provider output remains candidate data until reviewed.
- Product-level summary fields can cache selected keywords, but this table is the normalized keyword review surface.

## 10. `k_product_knowledge_risk_terms` 草案

Required field set:

- `id`
- `product_id`
- `term_en`
- `term_zh`
- `risk_type`
- `risk_reason`
- `suggested_action`
- `source`
- `status`: `candidate` / `confirmed` / `removed` / `false_positive`
- `created_at`
- `updated_at`
- `confirmed_by_user_id`
- `confirmed_at`

Minimum risk types:

- `medical_claim`
- `legal_claim`
- `safety_claim`
- `absolute_claim`
- `competitor_trademark`
- `regulated_product`
- `misleading_discount`
- `platform_policy_risk`
- `unsupported_performance_claim`

Design rules:

- Risk terms should support human confirmation and false-positive removal.
- Confirmed risk terms should be visible to later page generation, WooCommerce draft, and ad-material flows through the future K API.
- K04 does not implement blocking rules or formal approval gates.

## 11. `k_product_knowledge_research_runs` 草案

Required field set:

- `id`
- `product_id`
- `run_type`
- `status`: `queued` / `running` / `succeeded` / `failed` / `needs_review` / `cancelled`
- `requested_by_user_id`
- `target_market`
- `target_language`
- `seed_keywords_json`
- `serp_provider`
- `serp_result_summary_json`
- `chatgpt_filter_summary_json`
- `claude_filter_summary_json`
- `selected_keyword_ids_json`
- `error_class`
- `error_message`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

Design rules:

- K15 may later create a disabled keyword research skeleton.
- K16/K17/K18 live provider behavior waits for C14/C09 and owner approval.
- K04 does not call SERP, ChatGPT, Claude, n8n, or any live provider.
- Research runs store summaries and references, not provider secrets.

## 12. `k_product_knowledge_ai_events` 草案

Required field set:

- `id`
- `product_id`
- `research_run_id nullable`
- `event_type`
- `provider`
- `provider_model`
- `prompt_version`
- `input_hash`
- `output_summary_json`
- `output_payload_json`
- `status`
- `error_class`
- `error_message`
- `token_estimate`
- `cost_estimate`
- `created_at`
- `updated_at`

Design rules:

- Do not save secrets.
- Do not save provider keys.
- Do not read env files.
- Live provider execution waits for C14/C09 and owner approval.
- `input_hash` should identify input without forcing storage of sensitive or oversized prompt bodies.
- `output_payload_json` should store structured business output or summary only.
- Do not store secrets, provider keys, signed URLs, large prompts, image base64, or credential-like data.
- Raw provider response retention is disabled by default.
- Future raw response/debug retention requires C14/C09 and owner approval.
- Payload size/data retention policy must be reviewed before K05 if `output_payload_json` is included.

## 13. `k_product_knowledge_versions` 草案

Required field set:

- `id`
- `product_id`
- `version_number`
- `change_type`
- `changed_by_user_id`
- `change_source`
- `before_json`
- `after_json`
- `diff_json`
- `created_at`
- `updated_at`

Design rules:

- Version history must support manual edits.
- Version history must support AI draft changes.
- Version history must support keyword confirmation.
- Version history must support risk term confirmation.
- `version_number` should be monotonically increasing per product.
- K versions are product-domain history and do not replace future `operation_logs` integration.

## 14. `k_product_knowledge_media_assets` 草案

Required field set:

- `id`
- `product_id`
- `asset_type`
- `asset_role`
- `status`
- `review_status`
- `created_at`
- `updated_at`

Nullable until storage integration:

- `storage_provider`
- `object_key`
- `file_url_placeholder`
- `mime_type`
- `width`
- `height`
- `file_size`
- `source`
- `metadata_json`

Design rules:

- Media asset row may exist before physical storage exists.
- K04 does not connect MinIO or Filebrowser live services.
- This table is only a future data model for product media references.
- K05 must not require live storage fields.
- K05 must not create NOT NULL constraints for live storage fields before storage integration is approved.
- Future image-generation workflow design waits for the corresponding K/P/C tasks and owner approval.
- `file_url_placeholder` is not a secret and should not be treated as a live signed URL design.

## 15. `k_product_knowledge_review_items` 草案

Required field set:

- `id`
- `product_id`
- `review_type`
- `status`
- `severity`
- `title`
- `description`
- `proposed_changes_json`
- `decision_json`
- `created_by_user_id`
- `assigned_to_user_id`
- `reviewed_by_user_id`
- `reviewed_at`
- `created_at`
- `updated_at`

Design rules:

- Formal approval gates wait for C12.
- This table is only a K22 future placeholder design.
- K04 does not implement a parallel approval system.
- Review items may represent canonical data review, keyword review, risk review, media review, or readiness blockers.

## 16. 索引与约束草案

Product constraints:

- Unique `(workspace_key, business_context, product_key)`.
- Recommended partial unique `(workspace_key, business_context, sku)` where `sku is not null`.
- Index `(workspace_key, business_context, product_status)`.
- Index `(workspace_key, business_context, review_status)`.
- Index `parent_product_id` for variants.
- Index `variant_group_key` for variant grouping.
- Index `created_at`.
- Index `updated_at`.

Keyword constraints:

- Recommended unique `(product_id, lower(keyword_text), keyword_type, language_code, coalesce(market, ''))`.
- Index `(product_id, keyword_type)`.
- Index `(product_id, status)`.
- Index `(language_code, market)`.

Risk term dedupe:

- Recommended unique `(product_id, lower(term_en), risk_type)`.
- Index `(product_id, risk_type)`.
- Index `(product_id, status)`.

Research run indexes:

- Index `(product_id, status)`.
- Index `status`.
- Index `(target_market, target_language)`.
- Index `requested_by_user_id`.
- Index `started_at`.
- Index `created_at`.

Foreign key recommendations:

- K child tables should use foreign keys to `k_product_knowledge_products(id)`.
- `k_product_knowledge_ai_events.research_run_id` may reference `k_product_knowledge_research_runs(id)` and remain nullable.
- `k_product_knowledge_products.parent_product_id` may self-reference `k_product_knowledge_products(id)`.
- Do not add a foreign key to a not-yet-existing formal scope table until C18 is complete.
- User ID trace fields may be stored as UUID references by value during adapter-pending; whether to enforce user-table foreign keys should be reviewed before K05 to avoid coupling K schema to core user changes.

Created-at indexes:

- Every table should have a `created_at` index or a compound index where `created_at` is part of the expected review/query path.
- Tables with mutable review/status workflows should also have status plus created-time indexes.

## 17. K05 migration 风险提示

Future K05 may only:

- create `k_product_knowledge_*` tables;
- create indexes for K tables;
- create constraints for K tables.

Future K05 must not:

- alter core tables;
- alter `operation_logs`;
- alter `users`, `roles`, `permissions`, or `organizations`;
- alter formal scope tables;
- drop anything;
- modify existing migrations;
- run Alembic unless separately approved by the owner in the K05 task;
- connect Postgres, staging, production, or live services unless separately approved by the owner.
