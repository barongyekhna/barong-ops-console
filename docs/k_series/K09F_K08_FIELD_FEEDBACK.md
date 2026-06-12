# K09F K08 Field Feedback

Status: K09F docs-only feedback, pending owner review.

Date: 2026-06-12.

# 1. K09F 目标

K09F 只做 K08 字段体系回补检查。

- K09F 不改 K08 文档。
- K09F 不改 K09 code。
- K09F 不改 tests。
- K09F 是 K09A-E 完成后的字段体系反馈任务。
- `K09_TASK_PLAN.md` 中的 allowed output `K09_K08_FIELD_FEEDBACK.md` 已具体化为 `K09F_K08_FIELD_FEEDBACK.md`，以保持 K09F 子任务命名一致。

# 2. K09A-E 实际完成内容总结

- K09A 已定义单位存储与换算 baseline，包括 length、weight、future volume、future temperature、market display、conversion source、conversion precision、error/warning 和 human review rules。
- K09B 已定义 unit payload contract 和 JSON examples，包括 Unit Value Payload、`dimensions_json`、`package_dimensions_json`、`weight_json`、`package_weight_json`、future volume payload 和 future temperature payload。
- K09C 已新增 `backend/app/modules/k_series/product_knowledge/unit_conversion.py`，作为 K module-local pure helper。
- K09D 已新增 `tests/backend/modules/k_series/product_knowledge/test_unit_conversion.py`，覆盖 unit conversion non-DB tests。
- K09E 已新增 `backend/app/modules/k_series/product_knowledge/unit_payloads.py` 和 `tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py`，覆盖 dimensions / weight payload helper tests。
- K09E Docker pytest 已通过：`27 passed in 0.90s`。
- K09E 仍未接 `service.py` / `schemas.py` / `router.py` / `models.py` / `__init__.py`。
- K09E 仍未接 DB / API / frontend / staging / production / live services。

# 3. K08 字段覆盖检查

| Check item | Covered by K08? | Evidence from K08/K09 docs or code | Recommendation | K08B needed |
| --- | --- | --- | --- | --- |
| `dimensions_json` | yes | K08 field system lists `dimensions_json`; K08 dictionary defines it as product dimensions with original and normalized units; K09B section 3 and K09E `build_dimensions_payload` implement the nested contract. | Add a K08B note linking `dimensions_json` to the K09 Unit Value Payload contract and payload-level errors. | yes, low |
| `package_dimensions_json` | yes | K08 field system and dictionary list `package_dimensions_json`; K09B section 4 and K09E `build_package_dimensions_payload` keep package dimensions separate from product dimensions. | Add K08B clarification that package dimensions are shipping/package context and must not satisfy product-body dimension needs. | yes, low |
| `weight_json` | partial | K08 lists and describes `weight_json`; K09B section 5 and K09E `build_weight_payload` refine it into `net_weight` / optional `gross_weight`. | Clarify in K08B that product weight payload should distinguish net and gross where source data allows. | yes, medium |
| `package_weight_json` | yes | K08 lists and describes `package_weight_json`; K09B section 6 and K09E `build_package_weight_payload` separate package/shipping weight from product weight. | Add K08B note that package/shipping weight cannot backfill product net weight. | yes, low |
| dynamic attributes `attribute_unit` | yes | K08 dynamic attributes define `attribute_unit`; K08 review checklist says K09 should consume unit-bearing dynamic attributes; K09A keeps attribute schema unchanged. | Keep `attribute_unit` as future K09G/K09H input guidance; no table expansion needed. | no |
| future volume payload | partial | K09A/K09B define supported volume units and future payload shape; K08 dynamic attributes can carry category-specific unit fields but K08 does not explicitly name volume payload. | K08B can add future-only volume contract reference under dynamic attributes or dimensions/weight notes. | yes, low |
| future temperature payload | partial | K09A/K09B define supported temperature units and future payload shape; K08 does not explicitly name temperature payload. | K08B can add future-only temperature contract reference, with no DB/migration implication. | yes, low |
| `display_market` / `target_market` relationship | partial | K08 matrix and downstream mapping state `target_market` is readiness/request context and K09 uses `target_market` or `display_market`; K09C uses `display_market` with market fallback warnings. | K08B should clarify that `display_market` is payload-level display context and `target_market` is readiness/request context; either may inform display, but neither rewrites original values. | yes, low |
| `conversion_source` | partial | K08 field system says dimensions/weight should include conversion source; K08 downstream mapping lists conversion source; K09B section 9 and K09C/K09E implement source values. | K08B should link allowed `conversion_source` values to K09B rather than duplicating all nested fields as columns. | yes, low |
| `conversion_precision` | partial | K08 field system says normalized values should include explicit unit labels and conversion source; K08 dictionary notes package weight should preserve conversion precision; K09A/K09B/K09C define `conversion_precision`. | K08B should explicitly mention conversion precision for all four unit JSON fields, not only package weight notes. | yes, low |
| `warnings` / `errors` | partial | K08 readiness gates require blocked gates to provide errors/warnings; K09B and K09E payloads carry nested warnings/errors. | K08B should state that blocking unit payload errors must block downstream gates that depend on those dimensions/weights. | yes, medium |
| `review_status` | yes | K08 has product-level `review_status`; K09B defines payload-level `review_status`; K09E builders preserve payload-level review status. | Clarify product-level vs payload-level review states in K08B so unit payload `review_status` is not confused with product `review_status`. | yes, low |
| `reviewer_corrected` | partial | K09A/K09B define `reviewer_corrected`; K09C/K09E preserve it in nested Unit Value Payloads; K08 has reviewer identity/time but does not name this nested flag. | K08B should add `reviewer_corrected` as nested payload metadata and keep `reviewed_by_user_id` / `reviewed_at` as product/review evidence. | yes, low |
| `source_text` / `source_language` / `parsed_from_text` | partial | K08 raw input fields preserve source context; K09B/K09E include these metadata fields inside unit payloads. | K08B should clarify nested payload source metadata is narrower than product-level raw input and must not be fabricated. | yes, low |
| product vs package separation | yes | K08 uses separate product/package dimension and weight fields; K09B rules and K09E tests reject product/package key mixing. | Add K08B gate note that package data cannot satisfy product facts unless explicitly reviewed for that use. | yes, low |
| net vs gross weight separation | partial | K09B defines `net_weight`, `gross_weight`, `net_vs_gross_weight_ambiguous`; K09E warns on generic weight text; K08 only has generic `weight_json`. | K08B should explicitly document net/gross ambiguity and review requirement for product weight. | yes, medium |
| no AI guessing rule | yes | K08 field system and AI/human review policy say AI must not guess dimensions/weight or fabricate facts; K09B/K09E enforce `ai_guessing_forbidden`. | No immediate K08 change required; K08B can quote K09 unit-specific examples. | optional |
| no free-text parser rule | no | K09C/K09E reports and tests state no free-text dimensions parser; K08 allows future AI to parse explicit values but does not define this helper boundary. | K08B should clarify that K09C/E helpers do not parse free text and any future parser requires separate approval and review policy. | yes, medium |
| human review requirement | yes | K08 AI/human review policy requires human review for dimensions and weight; K09B payload states `needs_review`, `reviewed`, `reviewer_corrected`, `blocked`. | No blocker; K08B can add that unit payload review must be visible before shipping/display/publish-facing use. | optional |

# 4. 结论

- K08A 是否足以支持 K09A-E：partial。K08A 足以支撑 K09A-E 当前 docs-only / helper-only 范围，因为顶层字段、AI no-guessing、human review 和 readiness gate 原则都存在；但 K08A 没有完整吸收 K09B/K09E 形成的 nested unit payload 字段、unit error gate 行为、net/gross ambiguity 和 no free-text parser helper boundary。
- 是否需要立即修改 K08：no。K09F 本轮不修改 K08；当前差距不是 K09A-E helper 的运行 blocker。
- 是否建议创建 K08B：yes。建议 K08B 是 docs-only 小修。
- K08B 应只做以下文档修正：
  - 在 `K08_CANONICAL_FIELD_DICTIONARY.md` 中把四个 unit JSON 字段链接到 K09 Unit Value Payload contract。
  - 在 `K08_REQUIRED_OPTIONAL_FIELD_MATRIX.md` 中明确 product dimensions / package dimensions 和 product weight / package weight 的独立 gate behavior。
  - 在 `K08_READINESS_GATES.md` 中明确 unit payload blocking errors 会阻断依赖 dimensions/weight 的 downstream gates。
  - 在 `K08_AI_HUMAN_REVIEW_POLICY.md` 中补充 AI may structure provided unit values but cannot infer missing dimensions or net/gross/package distinction。
  - 在 `K08_DOWNSTREAM_CONSUMPTION_MAPPING.md` 中提到 K09 `unit_payloads.py` helper 是未来 runtime integration 的候选 contract helper，但 K08B 不接 runtime。
