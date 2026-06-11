# K05 Migration Review Checklist

Status: K05A review checklist, pending owner review.

Date: 2026-06-11.

## 1. Boundary Checklist

- [ ] Only creates K table family.
- [ ] No alter core tables.
- [ ] No alter `operation_logs`.
- [ ] No alter `users`, `roles`, `permissions`, `organizations`, or scope.
- [ ] No drop non-K tables.
- [ ] No existing migration modified.
- [ ] No backend runtime written.
- [ ] No frontend runtime written.
- [ ] No tests modified.
- [ ] No Docker run.
- [ ] No Alembic run.
- [ ] No Postgres connection.
- [ ] No staging run.
- [ ] No production run.
- [ ] No env read.
- [ ] No live services connected.

## 2. Migration Shape Checklist

- [ ] Downgrade only drops K tables.
- [ ] Downgrade drops K tables in reverse dependency order.
- [ ] Child tables reference `k_product_knowledge_products`.
- [ ] `k_product_knowledge_ai_events.research_run_id` references only the K research-runs table.
- [ ] No FK to formal scope table before C18.
- [ ] No FK to core users in K05A.
- [ ] K Scope Shim fields exist on products: `workspace_key`, `business_context`, `scope_mode`.
- [ ] Product defaults exist: `workspace_key`, `business_context`, `scope_mode`, `canonical_language`, `product_status`, `review_status`.
- [ ] `products.review_status` is required and defaults to `draft`.
- [ ] `products.review_status` lifecycle values are enforced or documented.
- [ ] Attributes value check rule is implemented or documented.
- [ ] Media storage fields remain nullable.
- [ ] AI events output retention rule is documented.
- [ ] K05B needs owner approval before running Alembic.

## 3. Alembic Head Safety Checklist

- [ ] Before K05B, verify current Alembic heads.
- [ ] Before K05B, verify down_revision still points to the accepted current head.
- [ ] If C series added migrations after K05A, rebase K branch and adjust down_revision before any Alembic run.
- [ ] Do not run Alembic if multiple heads exist.
- [ ] py_compile passed, but database migration execution still requires K05B owner approval.

## 4. Table Checklist

- [ ] `k_product_knowledge_products`
- [ ] `k_product_knowledge_attributes`
- [ ] `k_product_knowledge_translations`
- [ ] `k_product_knowledge_keywords`
- [ ] `k_product_knowledge_risk_terms`
- [ ] `k_product_knowledge_research_runs`
- [ ] `k_product_knowledge_ai_events`
- [ ] `k_product_knowledge_versions`
- [ ] `k_product_knowledge_media_assets`
- [ ] `k_product_knowledge_review_items`

## 5. Future Review Items

- [ ] Owner confirms partial unique SKU rule.
- [ ] Owner confirms expression unique keyword rule.
- [ ] Owner confirms expression unique risk-term rule.
- [ ] Owner confirms attribute repeatability rule.
- [ ] Owner confirms media object-key uniqueness rule.
- [ ] Owner confirms user trace strategy before any core user FK.
- [ ] Owner confirms K05B can run Alembic before any database execution.
