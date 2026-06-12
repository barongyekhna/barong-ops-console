# K08 Downstream Consumption Mapping

Status: K08A downstream mapping draft, pending owner review.

Date: 2026-06-12.

## 1. K07 frontend usage

K07 现在如做，只能 hidden-by-default，不挂正式菜单，不接正式 scope，不接 live provider。

List page fields:

- `id`
- `product_key`
- `product_name_en`
- `sku`
- `product_type`
- `brand_name`
- `product_status`
- `review_status`
- `image_asset_status`
- `primary_keyword`
- `category_path`
- `updated_at`

Create page fields:

- `product_key`
- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`
- `source_system`
- `source_record_id`
- optional `product_name_en`
- optional `product_type`
- optional `brand_name`
- optional `sku`
- hidden/system values `workspace_key`, `business_context`, `scope_mode`, `canonical_language`, `product_status`, `review_status`

Detail page fields:

- all system / identity fields
- canonical English fields
- raw input fields
- commercial fields
- dimensions / weight fields
- product facts
- SEO / feed / catalog fields
- media / visual fields
- AI / review fields
- dynamic attributes summary
- keyword and risk-term summaries

Edit page fields:

- editable canonical English fields
- editable raw source notes where allowed
- editable commercial fields
- editable dimensions / weight payloads
- editable product facts
- editable SEO/catalog fields
- editable media pointers
- editable dynamic attributes
- `manual_notes`

K07 unit input UI note:

- K07 unit input UI should use the K09 payload contracts for `dimensions_json`, `package_dimensions_json`, `weight_json`, and `package_weight_json`.
- K07 unit UI remains hidden-by-default until its own K07 gates approve menu/API/runtime exposure.
- K07 should show product dimensions separately from package dimensions, and product net/gross weight separately from package/shipping weight.
- K07 must not assume K09 helper existence means frontend or API integration is already approved.

Canonical review page fields:

- `deepseek_structured_output_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- `field_diff_json`
- canonical English fields
- product facts
- dimensions / weight
- claims/certifications
- `review_status`
- `reviewed_by_user_id`
- `reviewed_at`
- `manual_notes`

Keyword panel fields:

- `ready_for_keyword_research`
- `product_key`
- `product_name_en`
- `product_type`
- `category_hint`
- `primary_use_case_en`
- `short_description_en`
- `target_market`
- `primary_keyword`
- `secondary_keywords_json`
- `long_tail_keywords_json`
- future normalized keyword records

Risk term panel fields:

- `risk_keywords_json`
- `ai_warnings_json`
- product claims fields
- `certifications_json`
- `safety_note_en`
- future normalized risk-term records with English term, Chinese term, reason, suggested action, status and confirmation fields

Media panel fields:

- `main_image_url`
- `gallery_image_urls_json`
- `video_urls_json`
- `selected_image_path`
- `visual_profile_path`
- `image_asset_status`
- `media_notes_json`
- product identity fields needed to verify the selected image

## 2. K09 unit conversion usage

K09 must use the K08 dimensions / weight payloads:

- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`
- dynamic attributes with `attribute_unit`

Required payload concepts for K09:

- original value
- original unit
- normalized metric value and unit
- normalized imperial value and unit
- display market
- `target_market` when provided as readiness/request context
- conversion source
- conversion precision
- review status

K09 helper boundary:

- `backend/app/modules/k_series/product_knowledge/unit_conversion.py` and `backend/app/modules/k_series/product_knowledge/unit_payloads.py` exist as K module-local helpers / contract references.
- Their existence does not mean `service.py`, `router.py`, API, frontend, staging, production, or P-series integration is approved.
- K09C/K09E helpers accept already provided numeric value + unit inputs and preserve `source_text`; they do not parse free text or infer missing fields.

K09 rules:

- Preserve original operator/supplier input.
- Do not overwrite human-confirmed original values.
- Do not guess missing dimensions or weight.
- Market display should be derived from explicit market rules, `display_market`, or reviewed/resolved `target_market`.
- K09 uses `target_market` or `display_market` for unit display decisions, but K08A does not implement runtime storage.
- `display_market` is payload-level display context; `target_market` is readiness/request context. Either may inform display value selection, but neither rewrites original values or original units.
- K09 does not make unreviewed values publish-ready by converting them.

## 3. K10 DeepSeek mock adapter usage

K10 mock adapter input fields:

- `raw_input_text`
- `raw_input_language`
- `raw_input_payload_json`
- `source_system`
- existing canonical fields when present
- existing dimensions / weight fields when present
- existing product facts when present
- `manual_notes`

K10 mock adapter output fields:

- draft `product_name_en`
- draft `brand_name`
- draft `manufacturer`
- draft `product_type`
- draft `short_description_en`
- draft `long_description_en`
- draft `primary_use_case_en`
- draft `target_customer_en`
- draft structured product facts from provided input only
- draft dimensions / weight structure only when explicit values exist
- draft SEO suggestions
- draft keyword candidates
- draft risk-term candidates
- draft category hints
- `deepseek_structured_output_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- `field_diff_json`

K10 constraints:

- K10 mock must output K08 canonical field payload shape.
- K10 mock adapter should output separated values and units into the K09 contract shape.
- K10 mock must not rely on K09 helpers to parse free text such as `10 x 5 x 3 cm` or `weight: 2 lb`.
- K10 mock must not mark values reviewed or approved.
- K10 mock must not call live DeepSeek.

## 4. K12/K13 review interface usage

K12 English canonical review needs:

- canonical English fields
- AI draft fields
- `field_diff_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- raw input fields
- product facts
- dimensions / weight
- commercial fields where relevant
- claims / certifications / risk fields
- `review_status`
- `reviewed_by_user_id`
- `reviewed_at`
- `manual_notes`

K13 multilingual check needs:

- English canonical fields as source of truth
- `raw_input_text`
- `raw_input_language`
- future translation payloads
- `canonical_language`
- review state
- provider metadata only after future approved provider integration

K12/K13 rules:

- English canonical remains the master record.
- Other languages are review/display aids only.
- Ordinary machine translation is not acceptable as final multilingual review.
- Future DeepSeek V4 Pro integration waits for approved live-provider tasks.

## 5. K15/K19 keyword usage

K15 keyword research button reads:

- `ready_for_keyword_research`
- gate errors and warnings
- `product_key`
- `product_name_en`
- `product_type`
- `category_hint`
- `primary_use_case_en`
- `short_description_en`
- `target_customer_en`
- `target_market` or approved default market
- `review_status`

K15/K19 writes or edits:

- `primary_keyword`
- `secondary_keywords_json`
- `long_tail_keywords_json`
- `risk_keywords_json`
- future normalized keyword records with `keyword_text`, `keyword_type`, `language_code`, `market`, `search_intent`, `source`, `status`, `confidence`, `reason`, `reviewed_by_user_id`, `reviewed_at`

Keyword rules:

- `target_market` is readiness/request context, not a required products-table column in K08A.
- Product creation must not be blocked because `target_market` is missing.
- Keyword research must be blocked if no `target_market` or approved default market can be resolved.
- Target market resolution priority:
  1. Explicit keyword research request payload.
  2. Product/workspace default market setting.
  3. Owner-approved fallback default.
  4. Future `k_product_knowledge_research_runs.target_market`.
- Provider-generated keywords are candidates until reviewed.
- Operators can edit main keywords, secondary keywords, long-tail keywords and risk keywords.
- K15/K19 should treat unit payload warnings/errors as readiness or review context when keyword, feed, content, market display, or claims depend on dimensions or weight.
- K15 must not trigger live SERP/OpenAI/Claude/n8n calls unless future tasks and owner approval allow them.

## 6. K20 risk term usage

K20 risk term management reads:

- `risk_keywords_json`
- `ai_warnings_json`
- `short_description_en`
- `long_description_en`
- `seo_title_en`
- `seo_description_en`
- `certifications_json`
- `safety_note_en`
- `care_instructions_en`
- approved keywords and draft keyword candidates

K20 risk term records should include:

- English risk term
- Chinese risk term or explanation
- risk type
- reason
- suggested action
- source
- status
- confirmation user
- confirmation time

K20 actions:

- confirm risk term
- remove risk term
- mark false positive
- edit Chinese explanation
- edit reason
- edit suggested action

K20 rules:

- Risk terms are not automatically blocking unless future review rules define that behavior.
- Confirmed risk terms must be visible to readiness gates and future content/Woo/P-series consumers.
- K20 should treat unit payload warnings/errors as review context when risk, safety, compliance, shipping, dimensions, weight, package, or product claims depend on those values.
- K20 writes back to the K risk field model, not to P-series workflow JSON.

## 7. P-series future usage

- P 系列未来通过 Barong backend API 消费 K 字段。
- P 系列 future consumers should read reviewed canonical English fields, approved keywords, confirmed risk terms, reviewed dimensions/weight and reviewed media pointers.
- P-series future consumption must use Barong backend API and must not directly read or write the Barong DB.
- 不读取 Google Sheets `Product_Knowledge` 作为长期 source of truth。
- Existing P-series Google Sheets `Product_Knowledge` dependency remains future migration work and is not solved by K08B.
- Google Sheets may be a temporary import/source reference only if later approved, but not the master Product Knowledge store.
- n8n 不直接写 Barong DB。
- n8n future workflow calls must go through Barong backend API and K access/scope rules.
- K08A 不读取、不修改 P-series workflow JSON。
- K08A 不修改 n8n draft lane。
