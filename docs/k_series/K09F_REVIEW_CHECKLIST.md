# K09F Review Checklist

Status: K09F review checklist, pending owner review.

Date: 2026-06-12.

# 1. K09F 边界检查

- [x] 是否只创建 `docs/k_series/K09F_*.md`: yes.
- [x] 是否没有修改 K08 文档: yes.
- [x] 是否没有修改 K09 code: yes.
- [x] 是否没有修改 tests: yes.
- [x] 是否没有 Python code: yes.
- [x] 是否没有 frontend: yes.
- [x] 是否没有 migration: yes.
- [x] 是否没有 backend runtime 修改: yes.
- [x] 是否没有 router registration: yes.
- [x] 是否没有 Docker/Alembic/Postgres/staging/production: yes.
- [x] 是否没有 env: yes.
- [x] 是否没有 live services: yes.
- [x] 是否没有 P-series workflow JSON 读取/修改: yes.
- [x] 是否没有 n8n draft lane 修改: yes.

# 2. K08 feedback checklist

- [x] 是否检查 `dimensions_json`: yes.
- [x] 是否检查 `package_dimensions_json`: yes.
- [x] 是否检查 `weight_json`: yes.
- [x] 是否检查 `package_weight_json`: yes.
- [x] 是否检查 `attribute_unit`: yes.
- [x] 是否检查 `display_market` / `target_market` relationship: yes.
- [x] 是否检查 `conversion_source`: yes.
- [x] 是否检查 `conversion_precision`: yes.
- [x] 是否检查 `warnings` / `errors`: yes.
- [x] 是否检查 `review_status`: yes.
- [x] 是否检查 `reviewer_corrected`: yes.
- [x] 是否检查 `source_text` / `source_language` / `parsed_from_text`: yes.
- [x] 是否检查 product/package separation: yes.
- [x] 是否检查 net/gross separation: yes.
- [x] 是否检查 AI guessing forbidden: yes.
- [x] 是否检查 no free-text parser: yes.
- [x] 是否检查 human review requirement: yes.
- [x] 是否给出 K08B 建议: yes.
- [x] 是否给出下一步建议: yes.

# 3. K09F 后续进入条件

- If K09F recommends K08B, owner must approve K08B docs-only correction.
- If K09F recommends continuing K09, owner must approve K09G/K09H.
- K09I remains blocked.
- K09-SEAL remains blocked.
