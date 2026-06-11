# K04 Schema Review Checklist

Status: K04 review checklist draft, pending owner review.

Date: 2026-06-11.

## 1. K04 审核清单

- 是否只创建 `docs/k_series` 文件: yes.
- 是否没有 migration: yes.
- 是否没有 backend runtime: yes.
- 是否没有 frontend runtime: yes.
- 是否没有 tests: yes.
- 是否没有 Docker/Alembic/Postgres: yes.
- 是否没有 env: yes.
- 是否没有 live services: yes.

## 2. Schema 审核清单

- 是否只新增 K 表族: yes, design only.
- 是否没有 alter core tables: yes.
- 是否没有 `operation_logs` 表结构修改: yes.
- 是否包含 scope-adapter-pending 字段: yes, `workspace_key`, `business_context`, `scope_mode`.
- 是否支持 future C18 scope adapter: yes, by avoiding foreign keys to not-yet-existing scope tables.
- 是否支持 `product_key` / `sku` 唯一性: yes.
- 是否支持 variants: yes, through `parent_product_id` and `variant_group_key`.
- 是否支持 canonical English: yes.
- 是否支持 raw input: yes.
- 是否支持 translations: yes.
- 是否支持 keywords: yes.
- 是否支持 risk terms: yes.
- 是否支持 research runs: yes.
- 是否支持 AI events: yes.
- 是否支持 versions: yes.
- 是否支持 media assets: yes.
- 是否支持 review items: yes.
- 是否支持 unit conversion: yes.
- 是否支持 future P-series consumption: yes, through future Barong backend API only.
- `products.review_status` is required, has default `draft`, and has documented lifecycle values.
- `attributes` value fields have at-least-one-value rule and are not both NOT NULL.
- Media asset storage fields remain nullable until live storage integration is approved.
- `ai_events` output retention and secret exclusion rules are documented.

## 3. K05 进入条件

K05 may enter only after all of the following are true:

- K04 documents are reviewed and approved by the owner.
- ChatGPT review passes.
- Worktree is clean.
- Owner explicitly approves K05 migration.
- C series main worktree remains unaffected.
- K05 prompt explicitly allows only creating the K table family.

## 4. Boss open questions

- product_key 生成规则.
- SKU 是否在 workspace 内唯一.
- variant 处理深度.
- 默认 target market.
- 默认 currency.
- 是否允许 AI 自动写 canonical.
- DeepSeek live 何时允许.
- SERP provider 选择.
- ChatGPT / Claude model 选择.
- 风险词类型是否需要增减.
- 是否要保留 B2B 字段.
- 是否要支持多品牌 / 多站点.
- 是否要支持多 marketplace 字段.
- production 第一版是否 dormant release.
