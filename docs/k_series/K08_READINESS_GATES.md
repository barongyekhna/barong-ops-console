# K08 Readiness Gates

Status: K08A readiness gate draft, pending owner review.

Date: 2026-06-12.

## 1. Gate principles

- AI 不能绕过 readiness gate。
- 任何 blocked gate 必须给出 errors / warnings。
- 操作员可人工修正字段后重新检查。
- AI can explain missing fields, suggest draft values from provided input, and surface warnings.
- AI cannot mark a gate approved.
- Human reviewer or owner confirmation controls gate approval.
- K08A 只定义 gate，不实现代码。

Suggested gate result shape for future K tasks:

- `gate_key`
- `status`: `not_checked` / `ready` / `blocked` / `ready_with_warnings`
- `errors`
- `warnings`
- `checked_at`
- `checked_by`
- `approved_by_user_id`
- `approved_at`
- `source_fields_snapshot`

## 2. `ready_for_keyword_research`

- Gate purpose: Determine whether K15/K19 keyword research or manual keyword management has enough product identity and context.
- Required fields: `product_key`, `product_name_en`, `product_type` or `category_hint`, `primary_use_case_en` or `short_description_en`, `target_market` or approved default market, `review_status` not blocked.
- Blocking errors: missing product name, missing product type/category context, missing use case/short description context, no resolvable target market or approved default market, product archived, review status blocked.
- Warnings: raw input language uncertain, product type AI-suggested but not reviewed, weak use-case description, category hint low confidence.
- Target market rules: `target_market` is readiness/request context, not a required products-table column in K08A; product creation must not be blocked because it is missing, but keyword research must be blocked if no target market or approved default can be resolved.
- Target market resolution priority:
  1. Explicit keyword research request payload.
  2. Product/workspace default market setting.
  3. Owner-approved fallback default.
  4. Future `k_product_knowledge_research_runs.target_market`.
- Who can approve: operator, reviewer, or owner under future K access rules.
- AI role: identify missing fields, suggest draft keywords only after gate is ready, and explain uncertainty.
- Human role: review minimum fields, approve or fix context, and decide whether draft fields are acceptable for research.
- Downstream task unlocked: K15 keyword research button skeleton, K19 keyword candidate management.
- Suggested status fields: `ready_for_keyword_research`, `keyword_research_gate_errors_json`, `keyword_research_gate_warnings_json`.

## 3. `ready_for_category`

- Gate purpose: Determine whether category suggestion, category review, or marketplace classification can proceed.
- Required fields: `product_name_en`, `product_type`, `brand_name` if branded, `materials_json` when material affects category, `primary_use_case_en`, `target_customer_en` when audience affects category, existing `category_hint` or relevant dynamic attributes.
- Blocking errors: missing product type, insufficient product facts for category choice, blocked review status, unresolved material/category conflict, variant context missing when required.
- Warnings: category hint low confidence, brand/manufacturer unclear, materials unreviewed, product could fit multiple categories.
- Who can approve: category reviewer, operator, or owner.
- AI role: suggest category hints and confidence explanations from provided facts only.
- Human role: approve `category_path` or merchant category, resolve conflicts, and reject weak hints.
- Downstream task unlocked: category approval, page blueprint, Woo draft category mapping.
- Suggested status fields: `ready_for_category`, `category_gate_errors_json`, `category_gate_warnings_json`.

## 4. `ready_for_page_blueprint`

- Gate purpose: Determine whether a future page-structure blueprint can be generated without relying on fabricated facts.
- Required fields: `product_name_en`, `short_description_en`, `long_description_en` or page content source placeholder, `primary_use_case_en`, `target_customer_en`, reviewed keywords or accepted keyword placeholder, confirmed risk terms or no-risk confirmation, reviewed product facts relevant to the page.
- Blocking errors: missing core canonical fields, missing reviewed product facts for intended claims, keyword review blocked, risk review blocked, category unresolved when page structure depends on category.
- Warnings: long description is placeholder, keyword set incomplete, risk terms exist but are not yet fully resolved, target customer is broad.
- Who can approve: content reviewer, operator, or owner.
- AI role: propose page sections and identify unsupported claims.
- Human role: confirm facts, approve keywords and risk status, and decide whether placeholders are acceptable.
- Downstream task unlocked: future page blueprint generation.
- Suggested status fields: `ready_for_page_blueprint`, `page_blueprint_gate_errors_json`, `page_blueprint_gate_warnings_json`.

## 5. `ready_for_content_generation`

- Gate purpose: Determine whether AI/template content generation can proceed using reviewed canonical inputs.
- Required fields: canonical English fields needed for the content type, reviewed product facts, reviewed keywords, confirmed risk terms or no-risk confirmation, claims and certifications review, `category_path` or accepted category hint.
- Blocking errors: unreviewed product facts used as claims, unconfirmed certifications, unresolved risk terms, missing approved keywords, product review status blocked, AI warnings unresolved.
- Warnings: some optional selling points are missing, category path is accepted placeholder rather than final category, SEO title/description still draft.
- Who can approve: content reviewer, risk reviewer, operator, or owner depending on future workflow.
- AI role: generate draft content from reviewed inputs only, flag unsupported claims, and avoid new facts.
- Human role: review generated content and confirm claims, facts, keywords, SEO and risk status.
- Downstream task unlocked: future K14 selling-point refinement and page/content generation.
- Suggested status fields: `ready_for_content_generation`, `content_gate_errors_json`, `content_gate_warnings_json`.

## 6. `ready_for_media_work`

- Gate purpose: Determine whether media selection, visual profile work, or future image generation has enough product and visual context.
- Required fields: `product_name_en`, `product_type`, media source pointer such as `main_image_url`, `gallery_image_urls_json`, or `selected_image_path`, `image_asset_status`, `media_notes_json` when needed, `visual_profile_path` when visual profile work is requested.
- Blocking errors: no usable media pointer, image asset status blocked, product identity unclear, selected image unreviewed when required, media source contains unsafe or unsupported reference.
- Warnings: gallery missing, visual profile incomplete, image resolution/metadata unknown, media notes incomplete.
- Who can approve: media reviewer, operator, or owner.
- AI role: suggest visual notes or detect missing media context; AI cannot select final media without human review.
- Human role: choose or approve selected image, resolve media warnings, and confirm asset readiness.
- Downstream task unlocked: media panel work, future image generation, Woo draft media readiness.
- Suggested status fields: `ready_for_media_work`, `media_gate_errors_json`, `media_gate_warnings_json`.

## 7. `ready_for_woo_draft`

- Gate purpose: Determine whether a future WooCommerce draft can be generated through K API/backend integration.
- Required fields: `product_key`, `product_name_en`, `sku`, `product_type`, `regular_price` or price policy placeholder, `price_currency`, `stock_status`, `manage_stock`, `inventory_quantity` if managed, `short_description_en`, `long_description_en` or page content source placeholder, dimensions/weight when relevant, `category_path` or approved category, media readiness status, reviewed keywords when used, risk review not blocked.
- Blocking errors: missing SKU, missing price/currency, missing stock status, missing required descriptions, category not approved or accepted, relevant dimensions/weight missing or unreviewed, media blocked, risk review blocked, claims/certifications unresolved.
- Warnings: sale price present and needs discount-risk check, optional feed identifiers missing, image gallery incomplete, placeholder content source still unresolved.
- Who can approve: operator, commerce reviewer, risk reviewer, or owner depending on future workflow.
- AI role: validate completeness, surface warnings, and draft non-factual copy from reviewed inputs only.
- Human role: confirm commercial values, category, content source, risk status, media, and dimensions/weight.
- Downstream task unlocked: future WooCommerce draft generation.
- Suggested status fields: `ready_for_woo_draft`, `woo_draft_gate_errors_json`, `woo_draft_gate_warnings_json`.

## 8. `ready_for_publish_review`

- Gate purpose: Determine whether the product can enter a future final publish-review workflow.
- Required fields: all Woo draft minimum fields, reviewed canonical English fields, reviewed product facts, reviewed pricing and SKU, confirmed claims/certifications, reviewed risk terms, approved keywords, approved media selection, SEO reviewed, operation/review records present.
- Blocking errors: any Woo draft blocker still open, canonical facts unreviewed, price/SKU unreviewed, category unreviewed, unresolved risk terms, unsupported claims, media not reviewed, SEO not reviewed, missing review evidence.
- Warnings: optional feed identifiers missing, long-tail keywords incomplete, non-critical media notes still open, non-publish-critical attributes require later cleanup.
- Who can approve: owner or future formal reviewer after C12 approval gates are available.
- AI role: summarize blockers and warnings; AI cannot approve publish review.
- Human role: make final review decision, resolve or explicitly accept warnings, and record reviewer evidence.
- Downstream task unlocked: future publish review workflow. Formal approval still waits for C12.
- Suggested status fields: `ready_for_publish_review`, `publish_review_gate_errors_json`, `publish_review_gate_warnings_json`.
