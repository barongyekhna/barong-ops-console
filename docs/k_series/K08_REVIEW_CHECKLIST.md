# K08 Review Checklist

Status: K08A review checklist draft, pending owner review.

Date: 2026-06-12.

## 1. K08A 边界检查

- 是否只创建 `docs/k_series/K08_*.md`。
- 是否没有 Python code。
- 是否没有 frontend。
- 是否没有 tests。
- 是否没有 migration。
- 是否没有 Docker/Alembic/Postgres/staging/production。
- 是否没有 env。
- 是否没有 live services。
- 是否没有 P-series workflow JSON 读取/修改。
- 是否没有 n8n draft lane 修改。
- 是否没有 README.md 修改。
- 是否没有 CHANGELOG.md 修改。
- 是否没有 backend runtime 修改。
- 是否没有 frontend runtime 修改。
- 是否没有 core config / core permissions / core auth/deps 修改。
- 是否没有 router registration。

Expected K08A answer for all boundary checks: yes.

## 2. Field system checklist

- 是否覆盖 identity fields。
- 是否覆盖 canonical English fields。
- 是否覆盖 raw input fields。
- 是否覆盖 commercial fields。
- 是否覆盖 dimensions / weight fields。
- 是否覆盖 product facts。
- 是否覆盖 compliance / risk。
- 是否覆盖 SEO / feed / catalog。
- 是否覆盖 media / visual。
- 是否覆盖 AI / review。
- 是否覆盖 dynamic attributes。
- 是否定义 readiness gates。
- 是否定义 AI/human review policy。
- 是否支持 K07/K09/K10/K12/K15/K20。
- 是否支持 future P-series consumption through backend API only。
- 是否明确 English canonical fields 是主记录。
- 是否明确 AI draft 不得静默覆盖人工字段。
- 是否明确 AI 不得编造产品事实、claims、certifications、尺寸或重量。
- 是否明确 Google Sheets 不再作为长期 source of truth。
- 是否明确 n8n 不得直接写 Barong DB。

Expected K08A answer for all field-system checks: yes.

## 3. K08B / next step recommendation

- K08A 通过后，可进入 K09 或 K10。
- 如果要做 K07，应先做 K07A hidden UI information architecture。
- 不建议直接做 K07 正式菜单。
- 不建议直接接 live provider。
- 不建议直接接 P-series.
- K09 should consume `dimensions_json`, `package_dimensions_json`, `weight_json`, `package_weight_json`, and unit-bearing dynamic attributes.
- K10 should create a mock adapter payload that writes draft-only K08 field shapes without live DeepSeek.
- K12 should focus on canonical field diff review before any publish-facing use.
- K15/K20 should wait for readiness/risk field model alignment before provider integration.

## 4. K08B unit field clarification checklist

- 是否已记录 product-table vs JSON contract distinction。
- 是否已说明 nested K09 Unit Value Payload fields are not top-level product table columns。
- 是否已说明 unit payload errors affect readiness gates。
- 是否已说明 AI unit no-inference policy。
- 是否已说明 K09C/K09E helpers do not provide a free-text parser。
- 是否已说明 product/package dimensions separation。
- 是否已说明 product net/gross weight vs package/shipping weight separation。
- 是否已说明 K09 helper mention is contract reference, not runtime integration approval。
- 是否没有 code/runtime/migration changes。
