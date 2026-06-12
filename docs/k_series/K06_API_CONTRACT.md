# K06 API Contract

Status: K06A API contract draft, pending owner review.

Date: 2026-06-12.

Base path recommendation:

```text
/api/k/product-knowledge
```

## 1. API 总原则

- 所有 API 默认 disabled。
- 所有 API 需要 K access check。
- 所有 API 使用 K Scope Shim。
- 所有 API 只读写 `k_product_knowledge_*` 表族。
- 不调用 DeepSeek / SERP / ChatGPT / Claude。
- 不调用 n8n。
- 不调用 WooCommerce。
- 不写 Google Sheets。
- DELETE 不建议第一版硬删除。
- Archive should be soft archive by setting product lifecycle state to
  `archived`.
- Keyword research run is contract-only in K06A. K06B must not implement a live
  provider run.

Common adapter-pending scope fields:

```text
workspace_key = default_independent_store
business_context = independent_store
scope_mode = adapter_pending
```

Common product response fields:

- `id`
- `product_key`
- `product_status`
- `review_status`
- `canonical_language`
- `raw_input_text`
- `raw_input_language`
- `product_name_en`
- `brand_name`
- `manufacturer`
- `product_type`
- `short_description_en`
- `long_description_en`
- `primary_use_case_en`
- `target_customer_en`
- `sku`
- `workspace_key`
- `business_context`
- `scope_mode`
- `created_at`
- `updated_at`

Common error classes:

- `KFeatureDisabled`: feature flag is disabled; return 404 by default to keep
  the dormant API hidden, or 403 if the owner prefers explicit denial.
- `KUnauthenticated`: missing or invalid bearer token; return 401.
- `KAccessDenied`: K access check failed; return 403.
- `KProductNotFound`: product does not exist in the allowed K scope; return
  404.
- `KValidationError`: request payload or query is invalid; return 422.
- `KConflict`: unique key or idempotency conflict; return 409.
- `KInvalidState`: requested state transition is not allowed; return 409 or
  422, depending on existing project API style.
- `KProviderDisabled`: live provider action is not implemented or disabled;
  return 501 or 403 for future provider-run endpoints.

## 2. Endpoints

### 2.1 GET `/api/k/product-knowledge`

Purpose:

- List Product Knowledge records inside the K Scope Shim boundary.

Request fields:

- Query: `limit`, default 50, range 1-100.
- Query: `offset`, default 0, minimum 0.
- Query: `status`, optional product status filter.
- Query: `review_status`, optional review status filter.
- Query: `q`, optional text search over safe product identifiers and names.
- No request body.

Response fields:

- `items`: list of common product response fields.
- `count`
- `limit`
- `offset`

Permission key:

- `k.product_knowledge.read`

Operation log action:

- None for read-only list in the first version.

Idempotency behavior:

- Safe and idempotent. Repeated requests do not mutate data.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 by default.

Validation rules:

- `limit` must be 1-100.
- `offset` must be at least 0.
- Filters must use known lifecycle values.
- All queries are constrained by `workspace_key`, `business_context`, and
  `scope_mode`.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KValidationError`

### 2.2 POST `/api/k/product-knowledge`

Purpose:

- Create a new Product Knowledge master record.

Request fields:

- `product_key`, required unless K06B defines a deterministic server-generated
  key.
- `raw_input_text`, required.
- `raw_input_language`, required.
- `source_system`, optional, default `manual`.
- `source_record_id`, optional.
- `product_name_en`, optional at creation.
- `product_type`, optional at creation.
- `brand_name`, optional.
- `manufacturer`, optional.
- `sku`, optional.
- `short_description_en`, optional.
- `long_description_en`, optional.
- `primary_use_case_en`, optional.
- `target_customer_en`, optional.
- `manual_notes`, optional.

Response fields:

- Common product response fields.

Permission key:

- `k.product_knowledge.create`

Operation log action:

- `k.product_knowledge.created`

Idempotency behavior:

- Creating with an existing `(workspace_key, business_context, product_key)`
  returns `KConflict`.
- Optional future `idempotency_key` may be added later, but K06B should not
  invent a cross-module idempotency system.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- `product_key` must be stable, non-empty, and safe for lookup.
- `raw_input_text` must be non-empty.
- `raw_input_language` must be a valid language code or accepted project value.
- `canonical_language` defaults to `en`.
- `product_status` defaults to `draft`.
- `review_status` defaults to `draft`.
- System sets `workspace_key`, `business_context`, and `scope_mode`; clients
  must not override them in K06B.
- AI/provider fields may not be populated from live calls.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KValidationError`
- `KConflict`

### 2.3 GET `/api/k/product-knowledge/{product_id}`

Purpose:

- Return one Product Knowledge master record by K product id.

Request fields:

- Path: `product_id`.
- No request body.

Response fields:

- Common product response fields.
- Optional summary counts: `attributes_count`, `keywords_count`,
  `risk_terms_count`.

Permission key:

- `k.product_knowledge.read`

Operation log action:

- None for read-only detail in the first version.

Idempotency behavior:

- Safe and idempotent. Repeated requests do not mutate data.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 by default.

Validation rules:

- `product_id` must match the K product id type created by the K05 migration and
  K06B model.
- Product lookup must include the K Scope Shim filters.
- Archived products may be returned only if allowed by the first-version policy;
  otherwise return 404 for archived records.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`

### 2.4 PATCH `/api/k/product-knowledge/{product_id}`

Purpose:

- Update editable master product fields without overwriting reviewed canonical
  data silently.

Request fields:

- Optional editable canonical fields:
  `product_name_en`, `brand_name`, `manufacturer`, `product_type`,
  `short_description_en`, `long_description_en`, `primary_use_case_en`,
  `target_customer_en`.
- Optional source fields: `source_system`, `source_record_id`.
- Optional commerce and fact fields only if already present in the K05 table and
  accepted by owner review.
- Optional `sku`.
- Optional `manual_notes`.
- Optional `review_status`, only for allowed transitions.

Response fields:

- Common product response fields.
- `updated_fields`, optional list of changed field names.

Permission key:

- `k.product_knowledge.update`

Operation log action:

- `k.product_knowledge.updated`

Idempotency behavior:

- Repeating an identical patch should produce the same final product state.
- No-op patches should be accepted as idempotent or rejected as validation
  errors; K06B should choose one behavior and document it in code comments.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- Product must be inside the K Scope Shim boundary.
- `product_key`, `workspace_key`, `business_context`, `scope_mode`,
  `created_at`, and `created_by_user_id` are not client-editable.
- Archived products cannot be updated unless the owner approves restore or
  admin-edit behavior.
- AI draft fields must not overwrite reviewed canonical fields without explicit
  human review logic.
- Unique `sku` behavior must follow the K05 owner-confirmed rule.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`
- `KConflict`
- `KInvalidState`

### 2.5 POST `/api/k/product-knowledge/{product_id}/archive`

Purpose:

- Soft archive a Product Knowledge record. First version should not hard delete.

Request fields:

- `reason`, optional.

Response fields:

- Common product response fields.
- `archived`: true.

Permission key:

- `k.product_knowledge.archive`

Operation log action:

- `k.product_knowledge.archived`

Idempotency behavior:

- Archiving an already archived product should be idempotent and return the
  archived record, unless K06B chooses to return `KInvalidState`.
- No K child rows should be deleted.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- Product must be inside the K Scope Shim boundary.
- Archive sets product lifecycle state to `archived`.
- Archive must not delete product, attributes, keywords, risk terms, research
  runs, versions, media, or review items.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KInvalidState`

### 2.6 GET `/api/k/product-knowledge/{product_id}/attributes`

Purpose:

- List dynamic attributes for one product.

Request fields:

- Path: `product_id`.
- Query: `attribute_group`, optional.
- Query: `requires_review`, optional.

Response fields:

- `items` with `id`, `product_id`, `attribute_key`,
  `attribute_value_text`, `attribute_value_json`, `attribute_unit`,
  `attribute_group`, `source`, `confidence`, `requires_review`,
  `reviewed_by_user_id`, `reviewed_at`, `created_at`, `updated_at`.
- `count`

Permission key:

- `k.product_knowledge.read`

Operation log action:

- None for read-only attribute list in the first version.

Idempotency behavior:

- Safe and idempotent.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 by default.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- Optional filters must be bounded and safe.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`

### 2.7 PATCH `/api/k/product-knowledge/{product_id}/attributes`

Purpose:

- Replace or upsert the editable dynamic attribute set for one product.

Request fields:

- `items`: list of attributes.
- Each item: `attribute_key`, optional `attribute_value_text`, optional
  `attribute_value_json`, optional `attribute_unit`, optional
  `attribute_group`, optional `source`, optional `confidence`, optional
  `requires_review`.

Response fields:

- `items`: updated attribute list.
- `count`

Permission key:

- `k.product_knowledge.attributes.manage`

Operation log action:

- `k.product_knowledge.attribute.updated`

Idempotency behavior:

- Repeating the same payload should leave the same attribute state.
- If K06B implements full replacement, omitted existing attributes are removed
  or marked removed only if that behavior is explicit.
- If K06B implements upsert-only, omitted existing attributes are unchanged.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- Each item must have `attribute_key`.
- At least one of `attribute_value_text` or `attribute_value_json` must be
  present.
- Attribute repeatability must follow owner-confirmed K05 rules.
- AI may structure values from provided input only; K06B must not call live AI.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`
- `KConflict`

### 2.8 GET `/api/k/product-knowledge/{product_id}/keywords`

Purpose:

- List manually editable keyword candidates and approved keywords for one
  product.

Request fields:

- Path: `product_id`.
- Query: `keyword_type`, optional.
- Query: `status`, optional.
- Query: `language_code`, optional.
- Query: `market`, optional.

Response fields:

- `items` with `id`, `product_id`, `keyword_text`, `keyword_type`,
  `language_code`, `market`, `search_intent`, `source`, `status`,
  `confidence`, `reason`, `reviewed_by_user_id`, `reviewed_at`, `created_at`,
  `updated_at`.
- `count`

Permission key:

- `k.product_knowledge.read`

Operation log action:

- None for read-only keyword list in the first version.

Idempotency behavior:

- Safe and idempotent.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 by default.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- Filters must use accepted keyword type, status, language, and market values.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`

### 2.9 PATCH `/api/k/product-knowledge/{product_id}/keywords`

Purpose:

- Replace or upsert product keyword candidates and approved keywords.

Request fields:

- `items`: list of keywords.
- Each item: `keyword_text`, `keyword_type`, `language_code`, optional
  `market`, optional `search_intent`, optional `source`, optional `status`,
  optional `confidence`, optional `reason`.

Response fields:

- `items`: updated keyword list.
- `count`

Permission key:

- `k.product_knowledge.keywords.manage`

Operation log action:

- `k.product_knowledge.keyword.updated`

Idempotency behavior:

- Repeating the same payload should leave the same keyword state.
- Duplicate handling must follow the K05 normalized keyword uniqueness decision.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- `keyword_text`, `keyword_type`, and `language_code` are required.
- `keyword_type` should be one of `primary`, `secondary`, `long_tail`, `b2b`,
  `negative`, or `risk`.
- `status` should be one of `candidate`, `approved`, `rejected`, or `removed`.
- Provider-originated source values may be stored only as manual/mock data in
  K06B. No SERP, ChatGPT, Claude, DeepSeek, n8n, WooCommerce, or Google Sheets
  call is allowed.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`
- `KConflict`

### 2.10 GET `/api/k/product-knowledge/{product_id}/risk-terms`

Purpose:

- List product risk terms for policy, compliance, platform, and claim review.

Request fields:

- Path: `product_id`.
- Query: `risk_type`, optional.
- Query: `status`, optional.

Response fields:

- `items` with `id`, `product_id`, `term_en`, `term_zh`, `risk_type`,
  `risk_reason`, `suggested_action`, `source`, `status`,
  `confirmed_by_user_id`, `confirmed_at`, `created_at`, `updated_at`.
- `count`

Permission key:

- `k.product_knowledge.read`

Operation log action:

- None for read-only risk-term list in the first version.

Idempotency behavior:

- Safe and idempotent.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 by default.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- Filters must use accepted risk type and status values.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`

### 2.11 PATCH `/api/k/product-knowledge/{product_id}/risk-terms`

Purpose:

- Replace or upsert product risk terms.

Request fields:

- `items`: list of risk terms.
- Each item: `term_en`, optional `term_zh`, `risk_type`, optional
  `risk_reason`, optional `suggested_action`, optional `source`, optional
  `status`.

Response fields:

- `items`: updated risk-term list.
- `count`

Permission key:

- `k.product_knowledge.risk_terms.manage`

Operation log action:

- `k.product_knowledge.risk_term.updated`

Idempotency behavior:

- Repeating the same payload should leave the same risk-term state.
- Duplicate handling must follow the K05 normalized risk-term uniqueness
  decision.

Disabled-by-default behavior:

- If `K_PRODUCT_KNOWLEDGE_ENABLED=false`, return 404 before validation or
  writes.

Validation rules:

- Product must exist inside the K Scope Shim boundary.
- `term_en` and `risk_type` are required.
- `status` should be one of `candidate`, `confirmed`, `removed`, or
  `false_positive`.
- K06B must not implement automatic blocking rules or formal approval gates.
- K06B must not call live provider suggestions.

Error classes:

- `KFeatureDisabled`
- `KUnauthenticated`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`
- `KConflict`

### 2.12 Deferred contract: keyword research run

Purpose:

- Record the future contract for a keyword research button without implementing
  live provider execution in K06B.

Future path:

```text
POST /api/k/product-knowledge/{product_id}/keyword-research-runs
```

Request fields:

- `target_market`, required.
- `target_language`, required.
- `seed_keywords`, optional list.

Response fields:

- `run_id`
- `status`
- `product_id`
- `target_market`
- `target_language`
- `provider_calls_started`: false

Permission key:

- Future K15 permission key should remain K-prefixed. Suggested future key:
  `k.product_knowledge.keyword_research.run`.

Operation log action:

- Future suggested action: `k.product_knowledge.keyword_research.requested`.

Idempotency behavior:

- Future design should use an explicit idempotency key or dedupe by product,
  target market, target language, and seed hash.

Disabled-by-default behavior:

- Disabled in K06B. If present as a placeholder, return 404 or 501 without
  provider calls.

Validation rules:

- Must not call SERP, ChatGPT, Claude, DeepSeek, n8n, WooCommerce, or Google
  Sheets in K06B.
- Live provider behavior waits for C14/C09 and owner approval.

Error classes:

- `KFeatureDisabled`
- `KProviderDisabled`
- `KAccessDenied`
- `KProductNotFound`
- `KValidationError`

## 3. 权限 keys

K06 first-version API uses these K-prefixed permission keys:

```text
k.product_knowledge.read
k.product_knowledge.create
k.product_knowledge.update
k.product_knowledge.archive
k.product_knowledge.attributes.manage
k.product_knowledge.keywords.manage
k.product_knowledge.risk_terms.manage
```

K06B must not rewrite core permission runtime. If these permissions need to be
registered in the current permission registry, that registration point is
outside the isolated K module and requires owner approval.

## 4. operation_logs actions

Suggested first-version write actions:

```text
k.product_knowledge.created
k.product_knowledge.updated
k.product_knowledge.archived
k.product_knowledge.attribute.updated
k.product_knowledge.keyword.updated
k.product_knowledge.risk_term.updated
```

K06 does not change the `operation_logs` table structure. K06B may use the
existing operation log service or keep an internal placeholder only if owner
approval limits runtime edits.
