# PRE20-C Mock / Placeholder Audit

Date: 2026-06-16
Mode: static source audit only. No runtime, migration, UI, or code fix was executed.

Scope covered:

- `backend/app/`: API routes, services, schemas, repositories, middleware, sandbox, core registries.
- `frontend/`: route pages, API proxy allowlist, UI shells, client libraries.
- `services/`, `schemas/`, `api/`, `repositories/`, `middleware/`, `sandbox/`: resolved to the implemented paths under `backend/app/`; no separate top-level directories with these names are present.
- `tests/`: mock/demo fixtures and assertions were scanned but excluded from production endpoint totals.
- `docs/`: design and seal documents were scanned as evidence and excluded from production endpoint totals.
- `alembic/`: top-level `alembic/` is absent; actual migrations are under `backend/alembic/`.

Risk definition:

- P0: mock used in production-critical path.
- P1: partial feature misleading as real.
- P2: harmless placeholder, doc/test-only marker, or explicitly disabled shell.

### 🧾 1. Mock Function Inventory

| Module | Function | Type | Location | Risk |
|---|---|---|---|---|
| C01-C05 auth / RBAC | `RESERVED_ROLE_NAMES`, `RESERVED_ROLE_NOTES` | PLACEHOLDER | `frontend/src/components/user-management-panel.tsx` | P2: reserved role UI metadata; not a runtime mock. |
| C01-C05 auth / RBAC | permission/C18 integration completion flags | SCHEMA ONLY | `backend/app/schemas/permission.py:217` | P2: permission core is DB-backed, but C18 binding/storage completion markers remain false. |
| C06-C09 module system | `MODULE_MANIFESTS_V1.experimental.foundation_demo` | FAKE DATA | `backend/app/core/modules.py:186` | P1: mounted module represents demo-only data loop. |
| C06-C09 module system | `MODULE_MANIFESTS_V1.admin.settings` | PLACEHOLDER | `backend/app/core/modules.py:497` | P2: planned settings shell, metadata only. |
| C06-C09 module system | `MODULE_MANIFESTS_V1.business.products` | PLACEHOLDER | `backend/app/core/modules.py:546` | P1: product workspace exists as navigation/metadata placeholder only. |
| C06-C09 module system | `MODULE_MANIFESTS_V1.business.jobs` | FAKE DATA | `backend/app/core/modules.py:595` | P1: job module writes demo/metadata-only jobs, no business execution. |
| C06-C09 module system | `module_create` | FAKE DATA | `backend/app/api/routes/modules.py:86` | P1: action is `module.create_demo`. |
| C06-C09 module system | `agent_create` | FAKE DATA | `backend/app/api/routes/agents.py:52` | P1: creates foundation/demo agent metadata. |
| C06-C09 module system | `workflow_create` | FAKE DATA | `backend/app/api/routes/workflows.py:53` | P1: `execution=metadata_only`. |
| C06-C09 module system | `job_create` | FAKE DATA | `backend/app/api/routes/jobs.py:58` | P1: `execution=not_triggered`. |
| C06-C09 module system | `job_event_create` | FAKE DATA | `backend/app/api/routes/jobs.py:121` | P1: appends demo/metadata events, including `completed_demo`. |
| C06-C09 module system | `artifact_create` | FAKE DATA | `backend/app/api/routes/artifacts.py:56` | P1: `storage=metadata_only`; no file/object storage. |
| C06-C09 module system | `review_create` | FAKE DATA | `backend/app/api/routes/reviews.py:58` | P1: demo governance record only. |
| C06-C09 module system | `review_decision` | FAKE DATA | `backend/app/api/routes/reviews.py:88` | P1: `downstream_triggered=False`. |
| C06-C09 module system | `error_create` | FAKE DATA | `backend/app/api/routes/errors.py:52` | P2: safe operational/demo error record. |
| C06-C09 module system | `memory_event_create` | FAKE DATA | `backend/app/api/routes/memory.py:72` | P1: `model_called=False`; memory record only. |
| C06-C09 module system | `context_packet_create` | FAKE DATA | `backend/app/api/routes/memory.py:137` | P1: `model_called=False`; no model/context engine execution. |
| C06-C09 module system | `business.products.placeholder.adapter` | PLACEHOLDER | `backend/app/core/module_adapters.py:993` | P1: no API binding, placeholder component, mock execution type. |
| C06-C09 module system | `integration.n8n_test_bridge.adapter` | MOCK | `backend/app/core/module_adapters.py:1166` | P1: test bridge shell; n8n declared but not connected. |
| C06-C09 module system | `core.no_op_provider` | MOCK | `backend/app/core/execution_providers.py:371` | P0: production-shaped provider never executes business work. |
| C06-C09 module system | `core.mock_provider` | MOCK | `backend/app/core/execution_providers.py:392` | P0: safe mock provider in execution-provider registry. |
| C06-C09 module system | `core.contract_only_provider` | SCHEMA ONLY | `backend/app/core/execution_providers.py:413` | P0: metadata-only provider in execution chain. |
| C06-C09 module system | future provider contracts | PLACEHOLDER | `backend/app/core/execution_providers.py:434` | P1: future local/queue/webhook/scheduled/live providers are disabled placeholders. |
| C06-C09 module system | provider contract schema | SCHEMA ONLY | `backend/app/core/execution_providers.py:92` | P0: `persistence_policy=contract_only_no_persistence`. |
| C06-C09 module system | provider executable flags | SCHEMA ONLY | `backend/app/core/execution_providers.py:361` | P0: `executable=False`, `can_request_execution=False`. |
| C06-C09 module system | `build_execution_provider_access_state` | SCHEMA ONLY | `backend/app/services/execution_provider_registry.py:422` | P0: UI/API always receive no-execute access state. |
| C06-C09 module system | `module_adapter_registry`, `module_adapters_me` | SCHEMA ONLY | `backend/app/api/routes/module_adapters.py:20` | P1: read-only adapter contract API; no execution. |
| C06-C09 module system | `execution_provider_registry`, `execution_providers_me` | SCHEMA ONLY | `backend/app/api/routes/execution_providers.py:20` | P0: mounted provider API is contract/no-execute only. |
| C06-C09 frontend | `AdapterSurfaceShell` | PLACEHOLDER | `frontend/src/components/module-adapter-shell.tsx:380` | P1: UI states execution is not connected. |
| C06-C09 frontend | execution provider status shell | PLACEHOLDER | `frontend/src/components/execution-provider-status-shell.tsx:50` | P1: disabled action button; no request path. |
| C06-C09 frontend | provider client types | SCHEMA ONLY | `frontend/src/lib/execution-provider.ts:198` | P1: frontend type contract fixes `can_request_execution=false`. |
| C10-C12 sandbox | `SandboxRunner` | MOCK | `backend/app/sandbox/runner.py:253` | P0: deterministic mock lifecycle; no real runtime/process/network/DB/filesystem execution. |
| C10-C12 sandbox | `deterministic_mock_execution_response` | MOCK | `backend/app/sandbox/runner.py:833` | P0: returns safe mock result contract. |
| C10-C12 sandbox | `C09MockExecutionProviderInterface` | MOCK | `backend/app/sandbox/bridge.py:363` | P0: in-memory mock provider interface only. |
| C10-C12 sandbox | `SandboxExecutionBridge` | MOCK | `backend/app/sandbox/bridge.py:438` | P0: forwards contract-only copy and deterministic mock output. |
| C10-C12 sandbox | `SandboxRuntime.runtime_execute` | MOCK | `backend/app/sandbox/runtime.py:421` | P0: delegates only to C10E mock bridge. |
| C10-C12 sandbox | `SandboxRuntime.runtime_finalize` | MOCK | `backend/app/sandbox/runtime.py:478` | P0: finalizes disabled-execution mock-only state. |
| C10-C12 sandbox | resource enforcer | MOCK | `backend/app/sandbox/resource.py:69` | P0: `mode=mock_only`; policy-level resource control only. |
| C10-C12 sandbox | execution context lifecycle | MOCK | `backend/app/sandbox/execution_context.py:135` | P1: lifecycle is explicitly mock-only. |
| C10-C12 approval | `ApprovalRuleEngine` | MOCK | `backend/app/services/approval_rule_engine.py:48` | P1: auto-approval logic is limited to `mock` and `no_op`. |
| C10-C12 approval | `ApprovalWorkflowEngine` | IN-MEMORY ONLY | `backend/app/services/approval_workflow_engine.py:26` | P1: workflow engine creates in-memory state and does not execute actions. |
| C10-C12 approval | C12D approved-action boundary | SCHEMA ONLY | `backend/app/schemas/approval.py:86` | P1: schema explicitly states approved actions are not executed. |
| C13-C16 control plane | `ExecutionFlowGate` | SCHEMA ONLY | `backend/app/services/execution_flow_gate.py:63` | P0: validates contract chain only; does not execute work. |
| C13-C16 control plane | C13 C08 block rule | MOCK | `backend/app/services/execution_flow_gate.py:357` | P0: only `mock`/`no_op` adapter actions can pass the gate. |
| C13-C16 control plane | C13 C09 block rule | SCHEMA ONLY | `backend/app/services/execution_flow_gate.py:396` | P0: live/external provider path is blocked. |
| C13-C16 control plane | global kill switch state | IN-MEMORY ONLY | `backend/app/services/emergency_kill_switch.py:17` | P0: production-critical switch is process-local. |
| C13-C16 control plane | `get_global_kill_switch_state` / `set_global_kill_switch` | IN-MEMORY ONLY | `backend/app/services/emergency_kill_switch.py:93` | P0: state diverges across workers and restarts. |
| C13-C16 control plane | module switch policy engine | IN-MEMORY ONLY | `docs/C13C_MODULE_SWITCH_POLICY_LAYER.md:53` | P1: policy layer documented as read-only and in-memory. |
| C13-C16 control plane | AI execution binding registry | SCHEMA ONLY | `backend/app/api/routes/ai_execution_bindings.py:28` | P1: read-only fixed routing registry, no runtime/model call. |
| C13-C16 control plane | model lock registry | SCHEMA ONLY | `backend/app/api/routes/model_locks.py:30` | P1: static model lock registry and validation. |
| C13-C16 control plane | capability binding endpoints | SCHEMA ONLY | `backend/app/api/routes/capability_bindings.py:32` | P1: routing/validation model only. |
| C13-C16 control plane | module allocation endpoints | SCHEMA ONLY | `backend/app/api/routes/module_allocations.py:34` | P1: assignment/budget/enforcement contract only. |
| C13-C16 control plane | external dependency governance | SCHEMA ONLY | `backend/app/api/routes/external_dependencies.py:31` | P1: registry/gate checks declared intent only; no external service call. |
| C13-C16 control plane | `build_execution_prompt_payload` | SCHEMA ONLY | `backend/app/api/routes/execution_prompts.py:71` | P1: prompt generation status is returned without LLM/runtime invocation. |
| C13-C16 control plane | workflow registry endpoints | SCHEMA ONLY | `backend/app/api/routes/workflow_registry.py:35` | P1: workflow registry and invocation decision are contract/read-model only. |
| C13-C16 control plane | `webhook_gateway_ingress` | SCHEMA ONLY | `backend/app/api/routes/webhook_gateway.py:40` | P1: validates/gates webhook payload; does not dispatch n8n itself. |
| C13-C16 control plane | webhook gateway design endpoints | SCHEMA ONLY | `backend/app/api/routes/webhook_gateway.py:171` | P2: design/status metadata only. |
| C13-C16 control plane | payload standardization endpoints | SCHEMA ONLY | `backend/app/api/routes/payload_standardization.py:30` | P1: normalizes execution payload but does not execute it. |
| C13-C16 control plane | result normalization endpoints | SCHEMA ONLY | `backend/app/api/routes/result_normalization.py:31` | P1: normalizes result structures; no downstream action. |
| C13-C16 control plane | `CallbackExecutionStore` | IN-MEMORY ONLY | `backend/app/services/callback_handler.py:206` | P1: callback context/result store is process-local dict storage. |
| C13-C16 control plane | `callback_handler_receiver` | IN-MEMORY ONLY | `backend/app/api/routes/callback_handler.py:51` | P1: real-looking callback API writes to in-memory store. |
| C13-C16 control plane | `callback_handler_bind_context` | IN-MEMORY ONLY | `backend/app/api/routes/callback_handler.py:190` | P1: context binding not durable. |
| C13-C16 control plane | `DeadLetterQueueStore` | IN-MEMORY ONLY | `backend/app/services/failure_handling.py:202` | P1: DLQ is a process-local dict. |
| C13-C16 control plane | `failure_handling_submit_failure` | IN-MEMORY ONLY | `backend/app/api/routes/failure_handling.py:48` | P1: failure/DLQ API records are not durable. |
| C13-C16 control plane | `failure_handling_manual_replay` | PLACEHOLDER | `backend/app/api/routes/failure_handling.py:113` | P1: prepares recovery/replay plan, no real n8n dispatch. |
| C13-C16 demo bridge | `run_foundation_demo` | FAKE DATA | `backend/app/services/foundation_demo_service.py:243` | P1: writes DB demo records and completes `completed_demo` without real business work. |
| C13-C16 demo bridge | `foundation_demo_run` / `foundation_demo_latest` | FAKE DATA | `backend/app/api/routes/foundation_demo.py:20` | P1: mounted control-plane demo API. |
| C13-C16 demo bridge | foundation demo payload flags | FAKE DATA | `backend/app/services/foundation_demo_service.py:338` | P1: `demo_only=True`, `external_calls=False`, `real_business_task=False`. |
| C13-C16 demo bridge | `build_n8n_test_mock_response` | MOCK | `backend/app/services/n8n_test_http_client.py:4` | P1: deterministic mock dispatcher response; no HTTP I/O. |
| C13-C16 demo bridge | `run_n8n_test` | MOCK | `backend/app/services/n8n_test_service.py:257` | P1: creates `completed_demo` n8n records, external HTTP blocked. |
| C13-C16 demo bridge | `process_n8n_test_callback` | MOCK | `backend/app/services/n8n_test_service.py:559` | P1: callback can be accepted/blocked within mock-only terminal states. |
| C13-C16 demo bridge | `n8n_test_run`, `n8n_test_callback`, `n8n_test_latest` | MOCK | `backend/app/api/routes/n8n_test.py:32` | P1: mounted n8n test bridge, not a live n8n integration. |
| C13-C16 frontend | `FoundationDemoPanel` | FAKE DATA | `frontend/src/components/foundation-demo-panel.tsx:60` | P1: UI triggers demo-only run endpoint. |
| C13-C16 frontend | `N8nTestPanel` | MOCK | `frontend/src/components/n8n-test-panel.tsx:76` | P1: UI creates mock n8n result. |
| C13-C16 frontend | frontend API proxy allowlist for demo endpoints | MOCK | `frontend/src/app/api/backend/[...path]/route.ts:339` | P1: explicitly proxies foundation/n8n demo trigger APIs. |
| C17 observability | `EventEmitter` | IN-MEMORY ONLY | `backend/app/services/event_collector.py:67` | P0: audit event queue and recent buffer are process memory. |
| C17 observability | `DEFAULT_EVENT_EMITTER` | IN-MEMORY ONLY | `backend/app/services/event_collector.py:138` | P0: global process-local event collector. |
| C17 observability | `InMemoryStorageAdapter` | IN-MEMORY ONLY | `backend/app/services/storage_layer.py:350` | P1: side-effect-free list-backed storage adapter. |
| C17 observability | audit query local candidate cache | IN-MEMORY ONLY | `backend/app/services/audit_query_engine.py:689` | P1: query engine caches and reads adapter records locally. |
| C17 observability | `ExecutionReplayEngine` snapshot replay | MOCK | `backend/app/services/execution_replay.py` | P1: replay operates on captured snapshots/dry-run behavior unless a real executor is supplied. |
| C17 observability | anomaly rolling records | IN-MEMORY ONLY | `backend/app/services/anomaly_detection.py:574` | P1: streaming anomaly state is in process memory. |
| C17 observability docs | C17A in-memory event buffer | IN-MEMORY ONLY | `docs/C17A_AUDIT_EVENT_COLLECTOR.md:49` | P2: documentation confirms buffer-only collection. |
| C17 observability docs | C17D in-memory adapter | IN-MEMORY ONLY | `docs/C17D_STORAGE_LAYER.md:85` | P2: documentation confirms only in-memory adapter. |
| C18 multi-tenant OS | module binding registry | IN-MEMORY ONLY | `backend/app/services/module_binding_service.py:33` | P0: tenant/module visibility state is process-local dict. |
| C18 multi-tenant OS | `module_bind`, `module_bindings`, `org_visible_modules` | IN-MEMORY ONLY | `backend/app/api/module_binding.py:58` | P0: mounted C18D APIs mutate/read in-memory binding state. |
| C18 multi-tenant OS | module visibility lookup | IN-MEMORY ONLY | `backend/app/services/module_visibility_service.py:147` | P0: visibility reads the in-memory binding registry. |
| C18 multi-tenant OS | shared module registry | IN-MEMORY ONLY | `backend/app/services/shared_module_registry.py:49` | P0: shared modules are process-local dict state. |
| C18 multi-tenant OS | `_sync_c18d_binding` | IN-MEMORY ONLY | `backend/app/services/shared_module_registry.py:115` | P0: writes directly into C18D private in-memory registry. |
| C18 multi-tenant OS | shared module API routes | IN-MEMORY ONLY | `backend/app/api/shared_module.py:64` | P0: mounted APIs create/update/list non-durable shared modules. |
| C18 multi-tenant OS | module binding schema runtime storage | IN-MEMORY ONLY | `backend/app/schemas/module_binding.py:146` | P0: schema declares `process_memory_registry`, migration not executed. |
| C18 multi-tenant OS | organization/org-membership completion flags | SCHEMA ONLY | `backend/app/schemas/organization.py:578` | P1: module binding, cross-org query, and runtime migration flags remain false. |
| C18 multi-tenant OS | global contact directory schema | SCHEMA ONLY | `backend/app/schemas/global_contact.py:197` | P1: chat/UI/migration flags are false. |
| C19 IM system | direct conversation registry | IN-MEMORY ONLY | `backend/app/services/conversation_service.py:41` | P0: conversations are process-local dict state. |
| C19 IM system | `create_or_get_conversation` | IN-MEMORY ONLY | `backend/app/services/conversation_service.py:98` | P0: direct conversation creation has no DB persistence. |
| C19 IM system | `list_user_conversations_for_actor` | IN-MEMORY ONLY | `backend/app/services/conversation_service.py:155` | P0: list API reads only process registry. |
| C19 IM system | `GroupConversationReservedError` | PLACEHOLDER | `backend/app/services/conversation_service.py:37` | P1: group chat explicitly reserved. |
| C19 IM system | group conversation 501 mapping | PLACEHOLDER | `backend/app/api/routes/conversations.py:42` | P1: group creation returns 501. |
| C19 IM system | conversation API routes | IN-MEMORY ONLY | `backend/app/api/routes/conversations.py:67` | P0: mounted create/list/get APIs backed by memory registry. |
| C19 IM system | friend request registry | IN-MEMORY ONLY | `backend/app/services/messaging_permission.py:52` | P0: friend status/request state is process-local dict. |
| C19 IM system | `create_friend_request` | IN-MEMORY ONLY | `backend/app/services/messaging_permission.py` | P0: friend request writes no durable state. |
| C19 IM system | `accept_friend_request`, `reject_friend_request` | IN-MEMORY ONLY | `backend/app/services/messaging_permission.py` | P0: approval changes vanish on restart/worker switch. |
| C19 IM system | friend API routes | IN-MEMORY ONLY | `backend/app/api/routes/friends.py:46` | P0: mounted friend endpoints expose memory-only behavior. |
| C19 IM system | C19F completion status | SCHEMA ONLY | `backend/app/schemas/messaging_permission.py:427` | P1: UI/websocket/group/voice-video/migration flags false. |
| C19 IM system | `_ensure_default_global_im_boundary` | IN-MEMORY ONLY | `backend/app/services/cross_org_communication.py:44` | P0: mutates C18D in-memory binding as default IM boundary. |
| C19 IM system | `send_message_after_cross_org_check` | FAKE DATA | `backend/app/services/cross_org_communication.py` | P0: returns accepted message envelope without message persistence/websocket delivery. |
| C19 IM system | `send_message` | FAKE DATA | `backend/app/api/routes/messages.py:43` | P0: production-shaped send API returns fake success/no persistence. |
| C19 IM system | message permission check | IN-MEMORY ONLY | `backend/app/api/routes/messages.py:103` | P0: decision depends on memory-only friend/conversation state. |
| C19 IM system | message `_schema_only` | SCHEMA ONLY | `backend/app/api/routes/messages.py:35` | P1: helper returns 501 for schema-only operations. |
| C19 IM system | `get_messages` | SCHEMA ONLY | `backend/app/api/routes/messages.py:118` | P1: mounted API returns 501. |
| C19 IM system | `mark_messages_read` | SCHEMA ONLY | `backend/app/api/routes/messages.py:131` | P1: mounted API returns 501. |
| C19 IM system | message runtime notice | SCHEMA ONLY | `backend/app/schemas/message.py:608` | P1: `schema_only=True`, persistence false, migration false. |
| C19 IM system | attachment `_schema_only` | SCHEMA ONLY | `backend/app/api/routes/attachments.py:17` | P1: helper returns 501 for all attachment operations. |
| C19 IM system | `upload_attachment` | SCHEMA ONLY | `backend/app/api/routes/attachments.py:25` | P1: mounted upload API returns 501; no storage. |
| C19 IM system | `get_attachments` | SCHEMA ONLY | `backend/app/api/routes/attachments.py:41` | P1: mounted fetch API returns 501; no lookup. |
| C19 IM system | attachment runtime notice | SCHEMA ONLY | `backend/app/schemas/attachment.py:430` | P1: schema-only API contract; persistence/storage false. |
| C19 IM system | communication extensions API placeholders | PLACEHOLDER | `backend/app/schemas/communication_extensions.py:214` | P2: route not registered, execution not allowed. |
| C19 IM system | communication extensions completion status | SCHEMA ONLY | `backend/app/schemas/communication_extensions.py:335` | P2: schema-only future design, not mounted. |
| repositories | foundation demo repository | FAKE DATA | `backend/app/repositories/foundation_demo.py:10` | P1: DB repository stores demo job/event/artifact/review/memory projections. |
| repositories | n8n test repository | MOCK | `backend/app/repositories/n8n_test.py:87` | P1: DB repository stores n8n test/mock projections. |
| repositories | review demo decisions | FAKE DATA | `backend/app/repositories/reviews.py:10` | P1: maps decisions to `*_demo` statuses. |
| middleware | event collector middleware | IN-MEMORY ONLY | `backend/app/middleware/event_collector.py` | P1: request audit capture feeds C17 memory/log collector. |
| middleware | org/data/permission middleware | SCHEMA ONLY | `backend/app/middleware/org_context.py`, `backend/app/middleware/data_isolation.py`, `backend/app/middleware/permission.py` | P1: middleware participates in isolation, but C18D binding source remains memory-only. |
| tests | n8n mock dispatch fixtures | MOCK | `tests/backend/test_n8n_test_bridge_api.py:37` | P2: test-only guard blocks unmocked webhook and captures fake dispatch. |
| tests | sandbox mock-only tests | MOCK | `tests/backend/test_sandbox_execution_context.py:60` | P2: test-only assertion that C10 lifecycle is mock-only. |
| tests | communication extension schema tests | SCHEMA ONLY | `tests/backend/test_communication_extensions_schema.py:192` | P2: verifies placeholder/schema-only contract. |
| tests | foundation helper fixtures | FAKE DATA | `tests/backend/foundation_helpers.py:4` | P2: test fixtures use demo module/agent/workflow records. |
| docs | C09 provider docs | SCHEMA ONLY | `docs/C09_EXECUTION_PROVIDER_BACKEND.md:167` | P2: docs confirm no-op/mock/contract-only provider model. |
| docs | C10 sandbox docs | MOCK | `docs/C10_MODULE_SANDBOX_SEAL.md:5` | P2: docs confirm complete but non-executable mock sandbox. |
| docs | C19 attachment docs | SCHEMA ONLY | `docs/C19G_ATTACHMENT_SYSTEM_SCHEMA.md:87` | P2: docs confirm 501 placeholder and no upload/storage logic. |
| docs | C19 communication extension docs | PLACEHOLDER | `docs/C19H_COMMUNICATION_EXTENSIONS.md:97` | P2: docs confirm placeholders are not mounted/executable. |
| migrations | C19 runtime migrations | PLACEHOLDER | `backend/alembic/versions/` | P1: no managed migration for C19 messages, conversations, attachments, friend requests, or C18 module/shared-module registries. |
| migrations | foundation migration | FAKE DATA | `backend/alembic/versions/20260608_01_create_core_foundation_tables.py:1` | P1: durable tables exist for foundation/demo loop, not real workflow execution. |

### 🧱 2. System-wide Mock Map

**C01-C05 auth / RBAC**

- Core auth, sessions, users, roles, and permission assignment are mostly real and DB-backed.
- Mock/placeholder exposure is low: reserved role UI metadata, seed/static permission catalog behavior, and C18 permission-scope integration flags.
- Product risk: P2 for most auth/RBAC markers; no direct auth bypass mock found in this pass.

**C06-C09 module system**

- C07 module registry contains demo/foundation modules, planned settings, planned product workspace, and metadata-only job/workflow surfaces.
- C08 adapters expose safe shells and placeholders. `business.products.placeholder.adapter` is a visible product placeholder; `integration.n8n_test_bridge.adapter` is a test bridge.
- C09 providers are all no-op/mock/contract-only/future-disabled. `executable=False` and `can_request_execution=False` are hard-coded contract properties.
- Frontend mirrors this by disabling action submission and rendering "execution not connected" shells.
- Product risk: P0 for any production claim of execution readiness; P1 for users seeing product/job/provider surfaces that cannot perform real work.

**C10-C12 sandbox**

- C10 is intentionally mock-only: runner, bridge, provider interface, resource enforcement, execution context, and runtime finalization all return safe mock or disabled-execution states.
- C12 approval persistence exists, but approval rule/workflow engines do not execute approved actions. The workflow engine is in-memory.
- Product risk: P0 if sandbox is treated as a real execution environment; P1 for approval flows implying a real downstream execution.

**C13-C16 control plane**

- C13 execution gate validates a sealed contract chain; it does not execute work. Its valid path depends on `mock`/`no_op` actions and non-executable providers.
- C13 emergency kill switch is process-local memory, which is a production-critical P0.
- C14 and C14X registries/prompts are static or contract-only. Prompt generation returns payload/status without LLM invocation.
- C15 registry/gateway/callback/failure layers are mostly contract/read-models. Webhook ingress can accept/gate but does not dispatch live n8n. Callback store and DLQ are in-memory.
- Foundation Demo and n8n Test Bridge write durable demo records and show completed states, but no external n8n, AI, workflow, or business task is executed.
- Product risk: P0 for execution-readiness claims; P1 for UI/API flows that look successful but are demo/mock.

**C17 observability**

- Event collector uses process-local queue and ring buffer.
- Storage layer includes an explicit `InMemoryStorageAdapter`.
- Audit query, replay, and anomaly detection can operate over in-memory adapter records/snapshots/rolling windows.
- Product risk: P0/P1 because audit, replay, anomaly, and trace data can disappear, diverge across workers, or be incomplete.

**C18 multi-tenant OS**

- C18D module binding is a process-memory registry.
- Shared modules are process-memory records and mutate C18D private memory state.
- Module visibility and permission isolation depend on those in-memory bindings.
- Organization/org-membership/global-contact schemas still contain false completion flags for module binding, UI, chat, migration, and cross-org querying.
- Product risk: P0 because tenant/module visibility and cross-org boundaries will diverge under multi-worker or restart.

**C19 IM system**

- Conversations are in-memory; group chat is reserved and returns 501.
- Friend requests and friend status are in-memory.
- Message send can return accepted-looking output but has no DB persistence and no websocket delivery.
- Message history/read-state endpoints return 501.
- Attachments upload/fetch return 501 and schema says no storage/persistence.
- Advanced communication extensions are schema-only placeholders and not mounted.
- Product risk: P0 for IM send/friend/conversation production paths; P1 for 501/schema-only read/upload APIs; P2 for unmounted future extensions.

### ⚠️ 3. Critical Mock Dependencies

| Dependency | Evidence | Impact | Risk |
|---|---|---|---|
| C08 -> C09 -> C10 execution path is mock/contract-only | `execution_type` limited to `mock`/`no_op`; providers set `can_request_execution=False`; C10 runtime is `mock_only`. | Any "run action" feature cannot perform real work. | P0 |
| Frontend execution surfaces depend on disabled/no-execute backend state | `module-adapter-shell.tsx`, `execution-provider-status-shell.tsx`, provider client types. | Users see adapter/provider shells but cannot execute actions. | P1 |
| Foundation Demo creates successful-looking DB records | `run_foundation_demo` writes job/artifact/review/memory and `completed_demo`. | Demo success can be confused with workflow/business completion. | P1 |
| n8n Test Bridge creates mock n8n success | `build_n8n_test_mock_response`, `run_n8n_test`, `n8n_test_callback`. | UI/backend can report n8n completion without webhook execution. | P1 |
| C19 message send returns accepted result without persistence | `send_message_after_cross_org_check`, `send_message`. | Messages disappear; history/read-state APIs cannot confirm delivery. | P0 |
| C19 friend/conversation state is process-local | `_FRIEND_REQUESTS`, `_DIRECT_CONVERSATION_REGISTRY`. | IM permissions and conversations diverge across workers/restarts. | P0 |
| C18 module/shared-module binding is memory-only | `_MODULE_BINDINGS`, `_SHARED_MODULES`, `_sync_c18d_binding`. | Tenant/module visibility and access boundaries are not durable. | P0 |
| C13 kill switch is memory-only | `_global_kill_switch_enabled`. | Emergency stop is not cluster-wide and resets on restart. | P0 |
| C17 audit/event/storage path is memory-backed | `EventEmitter`, `InMemoryStorageAdapter`, anomaly rolling records. | Audit/replay/anomaly data can drop or split by worker. | P0 |
| C15 callback and DLQ are memory-only | `CallbackExecutionStore`, `DeadLetterQueueStore`. | Callback results and failed executions disappear or cannot be replayed reliably. | P1 |
| Alembic lacks C19/C18 runtime migrations | `backend/alembic/versions/` contains foundation/auth/approval/security migrations only. | Schema strings exist but runtime persistence is missing. | P1 |

### 🚨 4. Broken Feature List

**API exists but is not functional**

- `GET /api/app/messages/{conversation_id}` returns C19C 501 schema-only notice.
- `POST /api/app/messages/read` returns C19C 501 schema-only notice.
- `POST /api/app/attachments/upload` returns C19G 501 placeholder notice.
- `GET /api/app/attachments/{message_id}` returns C19G 501 placeholder notice.
- Group conversation creation can return C19D 501 reserved design.
- C19H communication extensions expose schema/API placeholder models but no mounted runtime routes.
- C09 execution provider APIs are mounted but read-only/no-execute.
- C14/C15 design endpoints are mounted but return registries, models, validations, or normalized payloads rather than execution.

**Frontend exists but backend is mock/placeholder**

- `/foundation-demo` runs `foundation-demo/run`, which creates demo-only DB records.
- `/n8n-test` runs `n8n-test/run`, which creates mock n8n results without external HTTP.
- `/products` is tied to `business.products.placeholder.adapter`, no product API or product persistence.
- Module adapter shell renders declared surfaces while execution remains disabled.
- Execution provider status shell displays readable provider contracts while action submit remains disabled.

**Backend exists but has no durable DB**

- C18 module bindings.
- C18 shared modules.
- C13 global kill switch.
- C15 callback context/result store.
- C15 dead-letter queue.
- C17 event collector buffer.
- C17 in-memory storage adapter.
- C17 anomaly rolling windows.
- C19 conversations.
- C19 friend requests/friend status.
- C19 message send boundary.

**Schema exists but no execution**

- C09 execution providers and future provider contracts.
- C10 sandbox runtime and resource enforcement.
- C12 approved-action execution boundary.
- C14 AI binding/model lock/capability allocation/prompt generation registries.
- C15 workflow registry, webhook gateway, payload standardization, result normalization.
- C19 message persistence, read state, websocket delivery, migration.
- C19 attachment storage, upload, retrieval, migration.
- C19 communication extensions.
- C18 organization/global-contact/module-binding completion surfaces.

### 📊 5. Mock Density Metrics

Counting basis: production-mounted route functions and production services were counted; test fixtures and docs were excluded from endpoint totals but included as evidence rows.

| Metric | Count | Notes |
|---|---:|---|
| Total mock/demo/placeholder endpoints | 54 | Includes foundation/n8n demo triggers, foundation metadata-only writes, C18 memory APIs, C19 memory/501 APIs, C15 callback/failure memory APIs, and C08/C09 no-execute registry APIs. |
| Total schema-only/control-contract APIs | 79 | Includes mounted design/read-model/validation/normalization APIs and direct C19 501 endpoints; group conversation 501 is conditional and counted separately in findings. |
| Total direct 501 endpoint functions | 4 | `get_messages`, `mark_messages_read`, `upload_attachment`, `get_attachments`; group conversation is a conditional 501 path. |
| Total in-memory production-shaped systems | 14 | C13 kill switch; C15 callback store; C15 DLQ; C17 event emitter; C17 storage adapter; C17 audit-query cache; C17 anomaly window; C18 module bindings; C18 shared modules; C18 module visibility dependency; C19 conversations; C19 friend requests; C19 cross-org default boundary mutation; C12 approval workflow engine. |
| Live execution providers | 0 | No C09 provider is executable or allowed to request execution. |
| Real sandbox runtimes | 0 | C10 runtime capability is mock-only/disabled-execution. |
| Real external n8n/LLM dispatch paths | 0 | n8n test and prompt generator return mock/contract-only results. |
| % of execution plane that is fake execution | 100% | C08-C15 execution chain contains only mock/no-op/contract-only flow; no live provider, real sandbox, real n8n dispatch, or LLM invocation was found. |
| C-series areas materially affected | 9 / 19 = 47% | C06-C19 except mostly-real C01-C05 contain major mock/schema/in-memory surfaces; among post-RBAC areas C06-C19, impact is 9 / 14 = 64%. |

**Product Impact Analysis**

What users think is real but is mock:

- Foundation Demo and n8n Test can show completed jobs, artifacts, reviews, memory events, and operation logs, but these are demo/mock records.
- Message send can appear accepted, but there is no message persistence, read history, or websocket delivery.
- Friend requests and conversations can appear to work in one process, but state is not durable.
- Module visibility/shared module APIs can appear to configure tenant boundaries, but the binding store is memory-only.
- Execution provider and adapter surfaces can appear to describe executable actions, but all submit/execution paths are disabled or mock-only.
- Callback, DLQ, replay, audit query, and anomaly views can appear operational while critical state is local memory or snapshot-derived.

What will break if deployed:

- Multi-worker deployments will split C18 module bindings, C18 shared modules, C19 conversations, C19 friend requests, C15 callback/DLQ state, C17 event buffers, C17 in-memory storage, anomaly windows, and the C13 kill switch.
- Restarting the process will lose module bindings, shared modules, kill switch state, conversations, friend requests, callback bindings/results, DLQ records, and non-durable observability data.
- IM read/history/attachment flows will return 501 or empty/missing state.
- Any business action, provider execution, sandbox run, n8n dispatch, or LLM prompt execution will not perform real work.
- Audit/replay/anomaly claims will be incomplete if based on process memory instead of durable storage.

What is safe to ignore temporarily:

- Test-only mocks and fixtures under `tests/`.
- Documentation statements under `docs/` when they are only describing future/staged behavior.
- Unmounted C19H communication extension placeholders.
- Explicitly disabled frontend shells when they are labeled as disabled/test/demo and not sold as functional.
- Reserved role names/settings/product placeholders if hidden from production users or clearly marked as future placeholders.

**PRE20-C Bottom Line**

The codebase has real foundation/auth/CRUD pieces, but runtime execution is not production-ready. The entire C08-C15 execution path is mock/no-op/contract-only, C17 observability has non-durable memory-backed components, C18 tenant/module binding is memory-only, and C19 IM has production-shaped endpoints backed by memory, fake send success, schema-only notices, and 501 placeholders.
