# K TASK MAPPING LAYER REPORT

Status: read-only mapping layer.

Date: 2026-06-13.

Scope: K01-K33 task-to-code-to-function mapping only. This document does not
rename K numbers, change runtime behavior, add features, register modules, run
migrations, or modify code.

## 1. Mapping Rules

This layer corrects the cognitive index of the K series without changing the K
numbering. K numbers are treated as historical task IDs. The mapping below is
the authoritative read-only relation between each K task, the actual repository
artifact, and the actual system function.

Status labels:

- REAL CODE EXISTS: real repository artifacts exist for the mapped function.
  For documentation/governance K tasks, this means the real artifact is a
  repository document rather than runtime code.
- PARTIAL IMPLEMENTATION: the mapped function has partial code, schema, UI,
  mock, constants, or isolated draft behavior, but is not complete or not
  fully wired.
- NOT IMPLEMENTED: no real implementation exists beyond planning, blocking
  notes, or meta-level intent.

## 2. Full K01-K33 Mapping Table

| K ID | Correct Mapping | Actual Artifacts / Code Pointers | Implementation Status | Notes |
| --- | --- | --- | --- | --- |
| K01 | docs baseline / system initialization | `docs/k_series/K_SERIES_MEMORY_BASELINE.md`, `docs/k_series/K_SERIES_TASK_PLAN.md`, `docs/k_series/K_SERIES_ISOLATION_RULES.md` | REAL CODE EXISTS | Baseline exists as documentation artifacts; no runtime behavior. |
| K02 | git worktree isolation (backend + infra) | `docs/k_series/K02_WORKTREE_ISOLATION_CHECKLIST.md` | REAL CODE EXISTS | Worktree isolation is documented; it is not a business module. |
| K03 | path allowlist / repo boundary rules | `docs/k_series/K03_ALLOWLIST_AND_DENYLIST.md` | REAL CODE EXISTS | Boundary rules exist as governance documentation. |
| K04 | schema layer (DB/product schema) | `backend/app/modules/k_series/product_knowledge/models.py`, `backend/app/modules/k_series/product_knowledge/schemas.py`, `docs/k_series/K04_PRODUCT_KNOWLEDGE_SCHEMA_DESIGN.md`, `docs/k_series/K04_PRODUCT_FIELD_TAXONOMY.md` | REAL CODE EXISTS | Product schema/model layer exists inside the isolated K table family. |
| K05 | migration layer (alembic) | `backend/alembic/versions/20260611_01_k_series_product_knowledge_tables.py`, `docs/k_series/K05_MIGRATION_DRAFT_NOTES.md` | REAL CODE EXISTS | K Product Knowledge Alembic migration exists; this mapping does not run Alembic. |
| K06 | backend API skeleton (not fully registered) | `backend/app/modules/k_series/product_knowledge/router.py`, `service.py`, `access.py`, `scope_shim.py`, `feature_flags.py` | PARTIAL IMPLEMENTATION | Backend skeleton exists but remains disabled/unregistered and adapter-pending. |
| K07 | frontend base UI (console shell) | `frontend/src/components/console-shell.tsx`, `frontend/src/lib/navigation.ts`, `frontend/src/app/(console)/layout.tsx` | REAL CODE EXISTS | Console shell exists, but this is platform UI rather than a fully exposed K module UI. |
| K08 | product field system (schema + UI partial) | `docs/k_series/K08_PRODUCT_FIELD_SYSTEM.md`, K product schema fields in `models.py` / `schemas.py`, K12 field surfaces | PARTIAL IMPLEMENTATION | Field taxonomy and schema exist; UI consumption is partial and not a complete K field management product. |
| K09 | unit conversion system (utility layer) | `backend/app/modules/k_series/product_knowledge/unit_conversion.py`, `unit_payloads.py`, K09 docs and tests | REAL CODE EXISTS | Utility layer exists and is sealed as non-runtime, non-live logic. |
| K10 | mock adapter system (deterministic AI mock) | `backend/app/modules/k_series/product_knowledge/k10_mock_adapter.py`, K10 docs and tests | REAL CODE EXISTS | Deterministic mock adapter exists; no live provider path. |
| K11 | live adapter (blocked by C14) | No live adapter code | NOT IMPLEMENTED | Blocked by C14 secret rules and C09 provider execution governance. |
| K12 | product review UI system (3-panel UI + workflow) | `frontend/src/modules/k12/product-review/ProductReviewPage.tsx`, `components/*`, `services/k12Api.ts`, `services/reviewState.ts` | REAL CODE EXISTS | Three-panel mock review workflow exists with diff, state, and version history. |
| K13 | AI analysis layer (risk/suggestion/score/overlay, NOT multilingual task) | `frontend/src/modules/k13/risk-engine/*`, `suggestion-engine/*`, `scoring-engine/*`, `overlay/*`, `services/*`, `types/*` | REAL CODE EXISTS | K13 is the local deterministic AI analysis layer; it is not the old multilingual review task. |
| K14 | selling point generation logic (partially embedded in K13) | `frontend/src/modules/k13/suggestion-engine/generateProductSuggestions.ts` | PARTIAL IMPLEMENTATION | Selling-point/suggestion behavior exists as embedded K13 logic, not as a separate K14 module. |
| K15 | keyword entry system (UI skeleton only) | Keyword fields in K schema; partial UI traces only | PARTIAL IMPLEMENTATION | Keyword persistence shape exists; complete keyword entry UX is not implemented. |
| K16 | SERP adapter schema (no execution layer) | `serp_provider`, `serp_result_summary_json`, and related schema/migration fields | PARTIAL IMPLEMENTATION | SERP data shape exists; no executable SERP adapter or live provider call. |
| K17 | ChatGPT filter adapter (schema/mock only) | AI/mock-related fields and K10/K13 local mock patterns | PARTIAL IMPLEMENTATION | No live ChatGPT adapter; any filtering concept is schema/mock-level only. |
| K18 | Claude filter adapter (schema/mock only) | AI/mock-related fields and K10/K13 local mock patterns | PARTIAL IMPLEMENTATION | No live Claude adapter; any filtering concept is schema/mock-level only. |
| K19 | keyword write system (partial backend traces) | `ProductKnowledgeKeyword*` DTOs, keyword table/model/service/router skeleton | PARTIAL IMPLEMENTATION | Backend traces exist for keyword read/patch, but module is unregistered and no complete workflow exists. |
| K20 | risk term management (partial logic only) | `ProductKnowledgeRiskTerm*` DTOs, risk-term table/model/service/router skeleton; K13 risk engine | PARTIAL IMPLEMENTATION | Risk analysis and risk-term data traces exist, but full management workflow is incomplete. |
| K21 | operation logs (constants only, no pipeline) | K operation constants in `backend/app/modules/k_series/product_knowledge/constants.py` | PARTIAL IMPLEMENTATION | Operation action names exist; no K operation logging pipeline is wired. |
| K22 | review workflow (partial schema + UI stub) | K schema `review_status`; K12 review UI/state machine | PARTIAL IMPLEMENTATION | Review concepts exist across K schema and K12 mock UI; no formal approval pipeline. |
| K23 | feature flag system (partial implementation) | `backend/app/modules/k_series/product_knowledge/feature_flags.py` | PARTIAL IMPLEMENTATION | Disabled-by-default local flag exists; not integrated with formal C13 module switch. |
| K24 | module manifest system (not fully implemented) | K module constants; platform module pages/registry outside K scope | PARTIAL IMPLEMENTATION | K has module identity constants, but no fully implemented formal manifest. |
| K25 | module registration (blocked by C07/C08/C13) | No registered K module in runtime | NOT IMPLEMENTED | Formal module registration remains blocked by C07/C08/C13. |
| K26 | scope system (blocked by C18) | `backend/app/modules/k_series/product_knowledge/scope_shim.py` | PARTIAL IMPLEMENTATION | K scope shim exists, but formal scope integration is blocked by C18. |
| K27 | secrets system (blocked by C14) | No K provider secret integration | NOT IMPLEMENTED | K10/K13 are mock-only; live provider secrets remain blocked by C14. |
| K28 | n8n integration (blocked by C15) | No K-to-n8n integration | NOT IMPLEMENTED | Existing n8n test bridge is platform/foundation only, not K integration. |
| K29 | staging system (not implemented) | No K staging artifact | NOT IMPLEMENTED | No K staging rollout evidence or staging system implementation. |
| K30 | production dormant release (blocked by C16) | No K production dormant release package | NOT IMPLEMENTED | Production dormant release remains blocked by release governance and owner approval. |
| K31 | production enable (blocked by C13/C16) | No K production enablement | NOT IMPLEMENTED | No production exposure or enablement exists. |
| K32 | P-system integration (blocked by C15) | No K/P integration | NOT IMPLEMENTED | No P-series workflow integration is implemented. |
| K33 | final system seal (meta-level only) | Existing K seal docs for subareas; no whole-system final seal | NOT IMPLEMENTED | K33 remains a future final acceptance/seal task. |

## 3. Real Implementation vs Partial vs Missing

### REAL CODE EXISTS

- K01: docs baseline / system initialization.
- K02: git worktree isolation documentation.
- K03: path allowlist / repo boundary documentation.
- K04: DB/product schema layer.
- K05: Alembic migration layer.
- K07: frontend console shell.
- K09: unit conversion utility layer.
- K10: deterministic AI mock adapter.
- K12: product review UI workflow.
- K13: local AI analysis layer.

### PARTIAL IMPLEMENTATION

- K06: backend API skeleton exists but is not fully registered.
- K08: product field system exists across docs/schema and partial UI consumption.
- K14: selling-point logic exists only as embedded K13 suggestion logic.
- K15: keyword entry system has schema/backend traces and UI skeleton only.
- K16: SERP adapter schema exists without execution.
- K17: ChatGPT filter adapter remains schema/mock only.
- K18: Claude filter adapter remains schema/mock only.
- K19: keyword write system has partial backend traces.
- K20: risk term management has partial logic/data traces.
- K21: operation log action constants exist without a pipeline.
- K22: review workflow is split between K schema and K12 UI stub.
- K23: disabled local feature flag exists without formal module-switch wiring.
- K24: module manifest identity exists only partially.
- K26: scope shim exists, but formal C18 scope integration is missing.

### NOT IMPLEMENTED

- K11: live adapter.
- K25: formal module registration.
- K27: provider secrets system.
- K28: n8n integration.
- K29: staging system.
- K30: production dormant release.
- K31: production enable.
- K32: P-system integration.
- K33: final whole-system seal.

## 4. Dependency Graph

### C-Series Gates

```text
C07/C08/C13 --> K25 module registration
C13         --> K23 formal feature/module switch replacement
C14         --> K11 live adapter
C14         --> K27 provider secrets system
C14 + C09   --> K16 SERP live execution
C14 + C09   --> K17 ChatGPT live filtering execution
C14 + C09   --> K18 Claude live filtering execution
C15         --> K28 n8n integration
C15         --> K32 P-system integration
C16         --> K30 production dormant release
C13 + C16   --> K31 production enable
C18         --> K26 formal scope integration
```

### K10-K13 Internal Dependency

```text
K10 deterministic mock adapter
  --> K12 mock canonical review surface
       --> K13 local AI analysis input

K12 review.ai_canonical
  --> K13A risk engine
  --> K13B suggestion engine
  --> K13C scoring engine
  --> K13D overlay panel
```

### K06 -> K07 -> K12 Chain

```text
K06 backend API skeleton
  -- not fully registered / disabled by flag -->
K07 frontend console shell
  -- UI host / console surface -->
K12 product review UI system
  -- mock local review workflow -->
K13 AI analysis overlay
```

### K13 -> K14 -> K15 Extension Chain

```text
K13 AI analysis layer
  --> K14 selling point generation logic
       currently embedded in K13 suggestion engine
  --> K15 keyword entry system
       currently schema/backend traces plus UI skeleton only
```

### Platform Access Chain

```text
K23 local feature flag
  --> K24 module manifest draft
       --> K25 formal module registration
            waits for C07/C08/C13

K06 scope shim
  --> K26 formal scope system
       waits for C18

K10/K13 mock-only AI
  --> K11/K16/K17/K18 live provider execution
       waits for C14 and, where applicable, C09
```

## 5. System Risk Analysis

### Semantically Confused K Tasks

- K13: historical task meaning was multilingual review, but the actual sealed
  implementation is AI analysis: risk, suggestion, scoring, and overlay. This
  is the main semantic mismatch and must be indexed as "AI analysis layer, NOT
  multilingual task."
- K14: intended selling-point generation is partially inside K13 suggestion
  logic, so K14 is not an independent module.
- K15: keyword research/entry intent is mixed with schema/backend traces and
  partial UI expectations.
- K22: review workflow meaning is split between K product schema status fields
  and K12 mock review UI behavior.

### Implementation Scattered Across Layers

- K08: product field system spans docs, DB models, Pydantic schemas, K09 unit
  payload rules, and K12/K13 UI consumption.
- K12: review behavior spans components, local mock API, state machine, diff
  viewer, and K13 overlay consumption.
- K13: analysis is split across risk engine, suggestion engine, scoring engine,
  services, types, and overlay.
- K19: keyword write traces span migration/model/schema/service/router skeleton,
  but not a registered runtime workflow.
- K20: risk-term traces span schema/model/service/router skeleton and K13 risk
  analysis logic.
- K21: operation log intent exists only as constants and is not connected to an
  operation-log write pipeline.

### Schema-Only Or Schema/Mock-Only K Tasks

- K16: SERP adapter has schema fields but no execution layer.
- K17: ChatGPT filter adapter is schema/mock only; no live adapter.
- K18: Claude filter adapter is schema/mock only; no live adapter.
- K19: keyword write system has backend schema/service traces but no registered
  end-to-end system.
- K20: risk term management has partial schema/service/risk-analysis traces but
  no complete management workflow.
- K22: review status schema and K12 mock UI exist, but formal approval remains
  absent.
- K24: module manifest exists only as identity/constants/draft-level metadata.
- K26: scope shim exists, but formal scope adapter is absent.

### Completed But Not Aligned With Original Numbering

- K09: utility layer is complete/sealed, but remains an isolated utility rather
  than a fully registered runtime capability.
- K10: deterministic mock adapter is complete/sealed, but K11 live adapter is
  still not implemented.
- K12: product review UI is complete/sealed as a mock local workflow.
- K13: implementation is complete/sealed as the AI analysis layer, but its
  historical label does not match the actual code.

### Structural Risks

- K numbering is no longer a reliable direct module locator.
- Several K tasks are spread across backend schema, frontend mock UI, and docs,
  so direct task-to-file lookup can create false confidence.
- Live-provider tasks remain blocked and must not be inferred from mock adapter
  or deterministic analysis code.
- Runtime registration is still a gate: unregistered backend skeleton code does
  not equal an enabled product module.
- Production/staging tasks have no implementation and must remain blocked until
  C-series release and integration gates are satisfied.

## 6. Conclusion

K system is logically fragmented but structurally traceable.

The K01-K33 sequence must remain unchanged, but future audits and task planning
should use this mapping layer as the lookup surface. The correct mental model is
not "K number equals code module"; it is "K number maps to actual artifacts,
implementation status, and dependency gates through this read-only layer."
