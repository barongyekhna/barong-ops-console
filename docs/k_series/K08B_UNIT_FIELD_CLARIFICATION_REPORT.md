# K08B Unit Field Clarification Report

Status: K08B docs-only clarification, pending owner review.

Date: 2026-06-12.

## 1. K08B 目标

K08B 根据 K09F feedback，对 K08 字段体系做文档级澄清，重点说明 K09 nested unit payload contract、产品表字段边界、readiness gate、AI/human review 和下游消费关系。

K08B 不写 Python code、不写 frontend、不写 tests、不创建 migration、不修改 backend/frontend runtime、不注册 router、不连接 live services、不读取 env、不读取或修改 P-series workflow JSON。

## 2. 修改的 K08 文档

- `docs/k_series/K08_PRODUCT_FIELD_SYSTEM.md`
- `docs/k_series/K08_CANONICAL_FIELD_DICTIONARY.md`
- `docs/k_series/K08_REQUIRED_OPTIONAL_FIELD_MATRIX.md`
- `docs/k_series/K08_READINESS_GATES.md`
- `docs/k_series/K08_AI_HUMAN_REVIEW_POLICY.md`
- `docs/k_series/K08_DOWNSTREAM_CONSUMPTION_MAPPING.md`
- `docs/k_series/K08_REVIEW_CHECKLIST.md`

## 3. K09F gap 对应修改点

| K09F gap | K08B clarification |
| --- | --- |
| Nested Unit Value Payload fields may be confused with product-table columns. | `K08_CANONICAL_FIELD_DICTIONARY.md` and `K08_PRODUCT_FIELD_SYSTEM.md` now state nested fields are JSON contract fields inside `dimensions_json`, `package_dimensions_json`, `weight_json`, and `package_weight_json`, not new table columns. |
| Product dimensions and package dimensions need explicit separation. | Dictionary, matrix, readiness gates, AI policy, and downstream mapping now state product dimensions cannot satisfy package dimensions and package dimensions cannot satisfy product dimensions. |
| Product net/gross weight and package/shipping weight need explicit separation. | Dictionary, matrix, readiness gates, AI policy, and downstream mapping now state package/shipping weight cannot backfill product net/gross weight, and generic `weight: 2 lb` is ambiguous without context. |
| Unit payload errors are not clearly tied to readiness gates. | Matrix and readiness gates now list blocking unit error codes and state dependent downstream gates must block when required values have unresolved errors. |
| AI policy needs unit-specific no-inference wording. | AI/human review policy now states AI may only structure provided numeric value + unit and must not infer missing dimensions, dimension order, net/gross, or product/package context. |
| K09C/K09E no free-text parser boundary is not visible in K08. | AI policy and downstream mapping now state K09C/K09E helpers preserve `source_text` but do not parse free text such as `10 x 5 x 3 cm` or `weight: 2 lb`. |
| `display_market` and `target_market` relationship is split across K08/K09 docs. | Dictionary, matrix, and downstream mapping now clarify `display_market` is payload-level display context and `target_market` is readiness/request context. |
| Future volume / temperature payloads are only in K09 docs. | Dictionary now references future volume / temperature payloads as dynamic / future-only contract references unless a category requires them. |
| K09 helper existence may be mistaken for runtime integration approval. | Downstream mapping now states `unit_conversion.py` and `unit_payloads.py` are module-local helpers / contract references and do not approve service, router, API, frontend, staging, production, or P-series integration. |

## 4. Boundary confirmation

- 是否修改 K09 docs/code/tests: no.
- 是否修改 backend runtime: no.
- 是否修改 frontend: no.
- 是否创建 migration: no.
- 是否注册 router: no.
- 是否运行 Docker/Alembic/Postgres/staging/production: no.
- 是否读取 env: no.
- 是否连接 live services: no.
- 是否读取/修改 P-series workflow JSON: no.
- 是否修改 n8n draft lane: no.

## 5. K08B 后建议下一步

- Owner review K08B docs-only clarification.
- If approved, K09G can proceed as a docs/design task for K07 unit input guidance, still hidden-by-default and without runtime integration.
- K09H can later align K10 AI mock adapter unit output rules with the clarified K08/K09 contract.
- K09I runtime integration remains blocked until owner approval and the deferred K06 runtime registration strategy are resolved.

## 6. 是否建议进入 K09G

Yes, after owner approval. K09G is a reasonable next step because K08B now clarifies the unit payload contract boundaries that K07 unit input guidance should consume. K09G still needs explicit owner approval and must not imply K09I runtime integration approval.
