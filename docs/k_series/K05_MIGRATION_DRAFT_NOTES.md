# K05 Migration Draft Notes

Status: K05A migration draft notes, pending owner review.

Date: 2026-06-11.

## 1. K05A Goal

K05A creates an Alembic migration draft for the isolated K Product Knowledge table family only.

This phase does not run Alembic, does not connect Postgres, does not run Docker, does not touch staging or production, and does not write backend runtime, frontend runtime, or tests.

## 2. Migration File

- Migration path: `backend/alembic/versions/20260611_01_k_series_product_knowledge_tables.py`
- Revision: `k05a_product_knowledge_001`
- Down revision: `c05b_permissions_001`
- K table-family prefix: `k_product_knowledge_`

## 2.1. Alembic Head / down_revision Safety

- Current draft down_revision is `c05b_permissions_001`.
- This was the observed down_revision in the K worktree at K05A generation time.
- The down_revision and current Alembic head must be revalidated before K05B or any Alembic run.
- If C series adds new migrations before merge, this migration must be rebased and down_revision must be adjusted.
- Do not run Alembic if multiple heads exist or if this migration is not based on the current accepted head.
- K05A `py_compile` success is not a database migration safety guarantee.

## 3. Tables Created

The migration creates these 10 K tables:

1. `k_product_knowledge_products`
2. `k_product_knowledge_attributes`
3. `k_product_knowledge_translations`
4. `k_product_knowledge_keywords`
5. `k_product_knowledge_risk_terms`
6. `k_product_knowledge_research_runs`
7. `k_product_knowledge_ai_events`
8. `k_product_knowledge_versions`
9. `k_product_knowledge_media_assets`
10. `k_product_knowledge_review_items`

## 4. Core Isolation

- Modify core tables: no.
- Modify `operation_logs` table structure: no.
- Modify `users`, `roles`, `permissions`, `organizations`, or scope tables: no.
- Create foreign key to formal scope table: no.
- Create foreign key to core `users` table: no.

User trace fields use nullable UUID values by value during `scope-adapter-pending`. They do not enforce foreign keys to core users.

## 5. Implemented Constraints And Indexes

Implemented in the migration:

- Product unique constraint on `(workspace_key, business_context, product_key)`.
- Product `review_status` is NOT NULL with default `draft`.
- Product `review_status` check constraint for `draft`, `ai_structured`, `needs_review`, `reviewed`, `approved`, `blocked`, `archived`.
- Product self-reference for `parent_product_id`.
- Child-table foreign keys to `k_product_knowledge_products.id`.
- `k_product_knowledge_ai_events.research_run_id` nullable K-only foreign key to `k_product_knowledge_research_runs.id`.
- Attribute value check: `attribute_value_text IS NOT NULL OR attribute_value_json IS NOT NULL`.
- Translation unique constraint on `(product_id, language_code, translation_type, source_text_hash)`.
- Keyword type and status check constraints.
- Risk-term status check constraint.
- Research-run status check constraint.
- Version unique constraint on `(product_id, version_number)`.
- Requested K indexes for product status/review/SKU lookup, child product lookup, research runs, AI events, versions, media assets, and review items.
- Media storage integration fields remain nullable.

## 6. Future TODO Constraints

Deferred for safety and compatibility review before K05B:

- Partial unique index on `(workspace_key, business_context, sku)` where `sku IS NOT NULL`.
- Normalized keyword uniqueness using `lower(keyword_text)` and `coalesce(market, '')`.
- Normalized risk-term uniqueness using `lower(term_en)`.
- Attribute uniqueness on `(product_id, attribute_key, attribute_group)`, pending owner confirmation that repeated attributes are not required.
- Partial unique media asset constraint on `(product_id, asset_role, object_key)` where `object_key IS NOT NULL`.
- Any future foreign keys to formal scope tables, pending C18.
- Any future foreign keys to core users, pending owner approval and adapter design.

## 7. AI Event Retention Rule

`k_product_knowledge_ai_events.output_payload_json` is present for structured business output or summaries only.

Raw provider response retention is disabled by default. K tables must not store provider secrets, provider keys, signed URLs, large prompts, image base64, or credential-like data.

## 8. K05B Owner Confirmations Needed

Before K05B or any Alembic run, the owner should confirm:

- Whether to run this migration against a local development database.
- Whether partial unique indexes are acceptable in project migration style.
- Whether expression-based uniqueness for normalized keywords and risk terms is acceptable.
- Whether K user trace fields should remain UUID-by-value or later map to core users.
- Product `product_status` lifecycle values.
- SKU uniqueness rule within workspace/business context.
- Attribute repeatability rules.
- Default target market and currency.
- AI event payload retention limits.
- Whether K05B is allowed to run Alembic.

## 9. K05A Execution Boundary

- Ran Alembic: no.
- Connected Postgres: no.
- Ran Docker: no.
- Ran staging scripts: no.
- Ran production scripts: no.
- Read env files: no.
- Connected live services: no.
- Wrote backend runtime: no.
- Wrote frontend runtime: no.
- Modified tests: no.
- Modified existing migrations: no.
