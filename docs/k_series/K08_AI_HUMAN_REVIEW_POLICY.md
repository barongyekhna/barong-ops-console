# K08 AI Human Review Policy

Status: K08A AI/human review policy draft, pending owner review.

Date: 2026-06-12.

## 1. AI 输出原则

- AI draft only until reviewed.
- AI 不得自动确认 facts。
- AI 不得自动确认 claims。
- AI 不得自动确认 certifications。
- AI 不得猜测尺寸重量。
- AI 不得静默覆盖人工字段。
- AI 可以建议 selling points / SEO / keywords / risk terms，但必须标记 draft。
- AI 可以从已提供输入中做结构化、英文润色、字段归类、风险提示和缺失项提示。
- AI 不得把未提供的材料、规格、产地、认证、库存、价格、税务、运输、保修或安全事实补成真值。
- AI draft 必须保留来源和 review 状态，不能直接变成 publish-facing canonical data。

Allowed AI draft targets:

- `deepseek_structured_output_json`
- `ai_confidence_scores_json`
- `ai_warnings_json`
- `field_diff_json`
- draft canonical suggestions before review
- draft SEO suggestions
- draft keyword candidates
- draft risk-term candidates
- draft category hints
- draft dynamic attributes from provided source text only

K08B unit-specific no-inference policy:

- AI may structure unit values only from provided numeric value + unit.
- AI must not infer missing dimensions.
- AI must not infer length / width / height order from free text such as `10 x 5 x 3 cm`.
- AI must not infer net weight vs gross weight.
- AI must not infer product weight vs package/shipping weight.
- AI must not infer package dimensions from product dimensions or product dimensions from package dimensions.
- AI-structured unit payloads remain draft / `needs_review` until human-confirmed.
- K09C/K09E helpers do not parse free text such as `10 x 5 x 3 cm` or `weight: 2 lb`.
- `source_text`, `source_language`, and `parsed_from_text` may preserve source metadata, but preserving source text does not mean the helper parsed it or approved it.
- Free-text parsing, if ever added, must be a separately approved K10/K09 parser task and still requires human review.

K08A 不接 live DeepSeek、OpenAI、Claude、SERP、WooCommerce、n8n、Google Sheets 或任何 live service。

## 2. Human review policy

必须人工确认字段:

- `product_name_en`
- `sku`
- price
- product facts
- dimensions
- weight
- claims
- certifications
- category
- keywords
- risk terms
- media selection

Human review rules:

- 人工确认字段优先级高于 AI draft。
- Operator/reviewer 可以 accept、edit、reject AI draft。
- AI draft 被 accept 后才可进入 canonical field 或 approved candidate 状态。
- 如果 operator 手动编辑 canonical 字段，AI 之后不得静默覆盖。
- 价格、库存、尺寸、重量、认证、产地、税务、运输、保修、安全说明、风险词确认和 media selection 必须由人工或批准来源确认。
- Review completion should record `reviewed_by_user_id` and `reviewed_at` where practical.

Suggested review states:

- `draft`
- `ai_structured`
- `needs_review`
- `reviewed`
- `approved`
- `blocked`
- `archived`

## 3. Field diff policy

- AI draft 与 canonical field 差异进入 `field_diff_json`。
- `field_diff_json` should show field key, current canonical value, AI draft value, diff reason, confidence/warning references, and proposed action.
- operator 可 accept / edit / reject。
- Accept means a human intentionally moves a draft value into canonical or approved status.
- Edit means the human writes a corrected value instead of copying the AI draft.
- Reject means the draft value must not be used downstream.
- 所有人工确认应记录 `reviewed_by_user_id` / `reviewed_at`。
- Future version records may snapshot before/after/diff in K-owned version tables.
- 未来 operation_logs 只通过 K21 接入，不改 `operation_logs` 表结构。

Field-diff handling by field type:

- Canonical English fields: draft suggestions require human review before write.
- Product facts: AI may only structure provided facts; review is mandatory.
- Commercial fields: AI may not populate values as facts.
- Dimensions / weight: AI may structure provided numeric value + unit into draft payloads, but cannot parse unsupported free text with K09C/K09E helpers, infer missing values, infer dimension order, or infer product/package/net/gross/shipping context.
- Keywords: AI/provider values remain candidates until approved.
- Risk terms: AI/provider values remain candidates until confirmed or removed.
- Media: AI can suggest notes, but selected media must be human-reviewed.

## 4. Multilingual policy

- English canonical 是主记录。
- 其他语言仅作为审核/展示辅助。
- 不允许普通机翻。
- 未来 DeepSeek V4 Pro 负责翻译。
- Future DeepSeek V4 Pro may translate, normalize, and structure multilingual product input into English canonical draft payloads.
- Multilingual review output must remain linked to the English canonical source and review state.
- Non-English translations must not become the source of truth for Product Knowledge.
- K08A 不接 live DeepSeek。

## 5. Downstream safety policy

- K07 must show draft vs reviewed state clearly in future UI.
- K10 mock adapter must emit K08-shaped draft payloads and warnings, not approved facts.
- K12 review interface must make field diffs explicit.
- K15 keyword research must read readiness and cannot start from blocked product records.
- K20 risk term management must support confirm, remove, and false-positive decisions.
- P-series future consumption must read reviewed K fields through Barong backend API only.
- n8n must not write directly to Barong DB.
