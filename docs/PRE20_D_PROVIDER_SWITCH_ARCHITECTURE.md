# PRE20-D Provider Switch Architecture

Date: 2026-06-16

Mode: architecture design and static source audit only. No C01-C19 code was
modified, no production request was executed, no live n8n endpoint was connected,
no real AI call was made, no UI was changed, and no deployment was performed.

PRE20-D defines the unified execution engine switch architecture for
`barong-ops-console`: a provider-routed execution model that can move from the
current mock-only system toward `mock`, `staging`, and `live` execution without
letting execution bypass C18H, C18F, C13, or C15.

## 1. Provider Architecture Diagram (Text)

Current and target request path:

```text
Frontend Request
  |
  v
C18H Org Context Middleware
  - org_id must come from authenticated server context
  - frontend-provided org_id is rejected
  - request_id / trace_id / active org are injected
  |
  v
C18F Permission Isolation
  - resolves module_id and action
  - C14/C15 execution-like paths map to execute
  - checks org membership, module binding, role action, module action
  |
  v
C13/C15 Control Plane Gate
  - C13 module switch / kill switch / execution flow gate
  - C15 workflow registry and module-workflow whitelist
  - C12 approval and C14 dependency/secret gates when required
  |
  v
ExecutionProviderRouter
  - resolves effective execution mode
  - applies environment, org, and module policies
  - rejects unsafe fallback and mode mismatch
  |
  +--> MockProvider
  |      - deterministic safe result
  |      - no network, no external provider, no production mutation
  |
  +--> StagingProvider
  |      - sandbox/test endpoint only
  |      - isolated staging secrets and n8n test bridge
  |      - no production credentials or production webhook
  |
  +--> LiveProvider
         - production provider only after explicit live gates
         - real n8n / AI / external API allowed only here
         - durable audit, idempotency, callback, and failure policies required

Provider Result
  |
  v
C15E Result Normalization + C17 Audit/Trace/Operation Log
  |
  v
Frontend Response
```

The router is the only place where provider class selection is allowed. C08
adapters, C09 provider contracts, C10 sandbox, C14 AI execution binding, and C15
workflow execution must submit normalized payloads to the router instead of
calling providers directly.

## 2. ExecutionProvider Interface Design

The common interface is intentionally small. Permission, org context, approval,
module switch, workflow binding, dependency policy, and result normalization are
not hidden inside a provider. They are mandatory upstream and downstream gates.

```python
from typing import Any, Literal, Protocol

ExecutionMode = Literal["mock", "staging", "live"]


class ExecutionContext:
    request_id: str
    org_id: str
    module_id: str
    adapter_key: str
    action_key: str
    actor_user_id: str
    effective_env: ExecutionMode
    required_permission: str
    c18f_permission_decision: dict[str, Any]
    c13_gate_decision: dict[str, Any]
    c15_workflow_decision: dict[str, Any] | None
    approval_ref: str | None
    idempotency_key: str
    audit_policy: dict[str, Any]
    timeout_policy: dict[str, Any]
    retry_policy: dict[str, Any]
    secret_binding_refs: list[str]


class ExecutionProvider(Protocol):
    mode: ExecutionMode

    def execute(
        self,
        payload: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        raise NotImplementedError
```

Interface rules:

- `execute(payload, context)` is the only runtime provider entrypoint.
- `context.effective_env` must match `provider.mode`.
- Providers must not perform C18F permission checks themselves; they must verify
  that a signed upstream permission decision exists.
- Providers must not select workflows themselves; C15A/C15F must already have
  produced an allowed workflow decision.
- Providers must not silently downgrade. If `live` is requested and unavailable,
  the result is a hard failure, not a mock result.
- Provider output must include `provider_mode`, `provider_key`,
  `execution_id`, `request_id`, `status`, `safe_summary`,
  `external_effect`, `production_effect`, and `normalization_version`.
- Raw provider errors, raw secrets, webhook URLs, tokens, local file paths, and
  model credentials must never be returned.

## 3. Mock / Staging / Live Implementations

### MockProvider

Purpose: preserve the current safe deterministic behavior.

```python
class MockProvider:
    mode = "mock"

    def execute(self, payload, context):
        assert context.effective_env == "mock"
        return {
            "provider_mode": "mock",
            "status": "succeeded",
            "external_effect": False,
            "production_effect": False,
            "safe_result_only": True,
            "result": deterministic_fake_result(payload, context),
        }
```

Behavior:

- Does not call external systems.
- Does not read live or staging credentials.
- May reuse C10 deterministic sandbox/bridge behavior.
- Must mark every result as `provider_mode=mock`.
- Must never be used as a fallback for a request whose effective mode is
  `staging` or `live`.

Current anchor points:

- `backend/app/sandbox/bridge.py` has `C09MockExecutionProviderInterface`.
- `backend/app/sandbox/runtime.py` finalizes disabled-execution mock-only state.
- `backend/app/services/n8n_test_service.py` creates demo/mock n8n records and
  blocks external dispatch.

### StagingProvider

Purpose: run integration-safe execution against isolated sandbox/test endpoints.

```python
class StagingProvider:
    mode = "staging"

    def execute(self, payload, context):
        assert context.effective_env == "staging"
        assert context.c18f_permission_decision["allowed"] is True
        assert context.c13_gate_decision["enforcement_result"] == "ALLOWED"
        return sandbox_or_test_endpoint_result(payload, context)
```

Behavior:

- Calls only sandbox/test endpoints.
- May call a staging n8n test bridge, never production n8n.
- Uses staging-scoped credentials only.
- Uses staging webhook references separate from C15A production refs.
- Writes durable staging audit records before and after dispatch.
- Blocks if the target endpoint, credential namespace, callback host, or storage
  bucket is not tagged `staging`.

Required isolation:

- Separate secret namespace: `staging/...`, not `production/...`.
- Separate callback namespace and signing key.
- Separate n8n base URL or test bridge.
- Separate artifact/storage namespace.
- Separate result marker: `provider_mode=staging`.

### LiveProvider

Purpose: perform real production execution after all execution gates have passed.

```python
class LiveProvider:
    mode = "live"

    def execute(self, payload, context):
        assert context.effective_env == "live"
        assert context.c18f_permission_decision["allowed"] is True
        assert context.c13_gate_decision["enforcement_result"] == "ALLOWED"
        assert context.audit_policy["durable"] is True
        return real_execution_result(payload, context)
```

Behavior:

- Calls real n8n, real AI providers, and real external APIs only through
  allowlisted connectors.
- Requires durable operation log, idempotency, timeout, retry, callback, DLQ,
  and failure policies.
- Requires C14 secret rules to resolve credentials by reference only.
- Requires C12 approval for high/critical or production-impacting actions.
- Requires explicit live intent and live-ready org/module/provider policies.
- Fails closed if any live precondition is missing.

LiveProvider must not exist as a default provider. It must be selected only when
global environment cap, org policy, module policy, provider contract, C18F,
C13/C15, C12, and C14 all allow live execution.

## 4. Routing Logic

The router resolves the effective execution mode and returns exactly one
provider instance.

```python
MODE_ORDER = {"mock": 0, "staging": 1, "live": 2}


class ExecutionProviderRouter:
    def resolve(self, module_id, org_id, env, context):
        assert context.c18f_permission_decision["allowed"] is True
        assert context.c13_gate_decision["enforcement_result"] == "ALLOWED"

        deployment_cap = env                         # mock | staging | live
        org_mode = org_policy.get(org_id, "mock")
        module_mode = module_policy.get(module_id, "mock")
        requested_mode = context.requested_env or module_mode

        effective_env = most_restrictive(
            deployment_cap,
            org_mode,
            module_mode,
            requested_mode,
        )

        if context.requested_env and context.requested_env != effective_env:
            raise ProviderModeMismatch(
                "Requested execution mode differs from effective policy mode."
            )

        if effective_env == "mock":
            return MockProvider()

        if effective_env == "staging":
            require_staging_ready(module_id, org_id, context)
            return StagingProvider()

        if effective_env == "live":
            require_live_ready(module_id, org_id, context)
            require_explicit_live_intent(context)
            return LiveProvider()

        raise UnknownExecutionMode(effective_env)
```

Policy precedence is safety-first:

1. Global deployment environment is a hard maximum capability.
2. Org policy can only keep or reduce that capability.
3. Module policy can only keep or reduce that capability.
4. Request-level mode can only select within the allowed envelope.
5. Missing policy defaults to `mock`.
6. Provider unavailability fails closed; it never falls back to mock.

Example:

```python
org_policy = {
    "org_1": "staging",
    "org_2": "mock",
    "org_3": "live",
}

module_policy = {
    "K-series": "staging",
    "C-series": "mock",
    "P-series": "live",
}
```

If `env=live`, `org_3=live`, and `P-series=live`, the router may select
`LiveProvider` only after explicit live gates pass. If any one of those is
`staging` or `mock`, the effective mode is reduced. If the caller explicitly
requested `live` but policy resolves to `mock`, the router rejects the request
instead of returning a mock success.

## 5. Module-Level Switching Strategy

Module policy controls the maximum execution mode for a module or module family.

```python
module_policy = {
    "K-series": "staging",
    "C-series": "mock",
    "P-series": "live",
    "integration.n8n_test_bridge": "staging",
    "business.products": "mock",
    "experimental.foundation_demo": "mock",
}
```

Rules:

- `mock`: module can only use MockProvider.
- `staging`: module can use MockProvider for explicit mock runs and
  StagingProvider for staging runs; it cannot use LiveProvider.
- `live`: module is eligible for LiveProvider but still requires org policy,
  deployment cap, provider readiness, C18F, C13/C15, C12, and C14.
- Module policy must be stored as data, not hard-coded in adapter execution
  code.
- C08 action contracts must declare allowed provider modes per action.
- C15F `allowed_workflows` must remain module-owned; no cross-module workflow
  selection is introduced by provider switching.

Recommended initial module classification:

| Module / family | PRE20-D mode | Reason |
|---|---:|---|
| `C-series` control-plane modules | `mock` | Current C13/C14/C15 surfaces are contract/read-model/no-execute. |
| `integration.n8n_test_bridge` | `staging` candidate | Already has test bridge shape, but external dispatch is currently blocked. |
| `business.products` placeholder | `mock` | Current adapter is placeholder/no real business execution. |
| `experimental.foundation_demo` | `mock` | Demo records can look successful but are not real workflow execution. |
| Future `K-series` integration modules | `staging` candidate | Suitable for sandbox/test endpoint validation before live. |
| Future `P-series` production modules | `live` candidate | Only after full live readiness and durable execution controls. |

## 6. Org-Level Switching Strategy

Org policy controls which organizations may use staging or live execution.

```python
org_policy = {
    "org_1": "staging",
    "org_2": "mock",
    "org_3": "live",
}
```

Rules:

- Org policy is evaluated after C18H resolves authenticated org context.
- Frontend-provided org identity is never trusted for provider routing.
- Live org policy requires a live enrollment record, owner/admin governance, and
  an auditable activation timestamp.
- Org live eligibility does not imply every module is live. Module policy and
  provider contract must also be live-ready.
- Org staging must use staging credentials and callback endpoints scoped to that
  org or to a controlled shared sandbox tenant.
- Org policy must fail closed if C18D module binding is unavailable or
  non-durable.

Org policy should include:

```text
org_id
max_execution_env
enabled_modules
live_enabled_at
live_enabled_by
staging_secret_namespace
live_secret_namespace
callback_namespace
audit_required
```

## 7. Environment-Level Switching Strategy

Environment switching is a deployment-level maximum, not an unconditional
provider selection.

```text
EXECUTION_ENV_CAP=mock     -> only MockProvider can execute
EXECUTION_ENV_CAP=staging  -> MockProvider or StagingProvider can execute
EXECUTION_ENV_CAP=live     -> MockProvider, StagingProvider, or LiveProvider
                              can execute, but only under matching org/module
                              policies and explicit request mode
```

Rules:

- `mock` is the default when no environment is configured.
- `staging` must never access production credentials, production n8n, or
  production callback URLs.
- `live` must never auto-enable live provider execution just because the process
  runs in production.
- A production deployment may still run mock-only modules, but live requests must
  not receive mock results.
- Staging/live endpoint references must be separated by type, namespace, and
  validation pattern.
- `env` is a server-side configuration and policy input; it is not trusted from
  arbitrary frontend payloads.

## 8. Security Isolation Model

Hard requirements:

- Mock cannot leak into live.
- Live execution cannot be triggered accidentally.
- Staging is isolated sandbox.
- All execution passes C18F permission layer.
- All execution passes C13/C15 control plane.

Controls:

| Risk | Required control |
|---|---|
| Mock result appears as live success | Result must carry `provider_mode`; live request rejects non-live provider result. |
| Live accidental trigger | Require deployment cap `live`, org live policy, module live policy, provider live-ready status, explicit live intent, C18F execute allow, C13/C15 allow, C12 approval when needed, C14 secret rule allow. |
| Staging touches production | Separate staging connector registry, secret namespace, callback host, storage namespace, and n8n base URL; deny production markers in staging config. |
| Provider bypasses C18F | Router requires signed/stored `c18f_permission_decision.allowed=True`. Future execution endpoints must be under C18F-covered `/api/app` or `/api/control-plane` paths. |
| Provider bypasses C13/C15 | Router requires C13 gate decision and C15 workflow binding decision before provider resolution. |
| Unsafe fallback | No automatic fallback across modes. Provider unavailable returns blocked/failed result. |
| Secret leak | C14 resolves secret refs; provider receives references or scoped clients, never raw secret values in result. |
| Cross-org execution | C18H server context and C18D module binding are used; frontend org_id is rejected. |
| Duplicate live execution | Idempotency key required before provider dispatch. |
| Callback spoofing | Signed callback namespace per env; durable callback context required before staging/live. |
| Audit gaps | Durable operation log and execution trace are required for staging/live. |

Live execution readiness checklist:

```text
[ ] C18H org context injected
[ ] C18F execute permission allowed
[ ] C13 module switch ON
[ ] C13D kill switch not active
[ ] C13E execution flow allowed for target mode
[ ] C15A workflow registered and active
[ ] C15F workflow whitelisted for module
[ ] C12 approval satisfied when required
[ ] C14 secret/dependency rule allows target connector
[ ] provider contract status is live_ready
[ ] org_policy allows live
[ ] module_policy allows live
[ ] deployment cap allows live
[ ] explicit live intent present
[ ] durable operation log opened
[ ] idempotency key reserved
[ ] timeout/retry/callback/failure policies loaded
```

## 9. Migration Strategy From Mock-Only System

### Phase 0: PRE20-D design only

Status now. Produce the architecture document and static audit mapping. Do not
modify runtime code, UI, deployment, provider connectors, live n8n, or AI calls.

### Phase 1: Introduce provider interface and router contracts

Future work:

- Add `ExecutionProvider` interface and `ExecutionProviderRouter`.
- Add `ExecutionMode = mock | staging | live`.
- Add server-side env cap, org policy, and module policy models.
- Add mode-aware provider result contract.
- Keep all actual runtime output mock until interface tests pass.

### Phase 2: Wrap current mock runtime as MockProvider

Future work:

- Route existing C10 mock sandbox and C09 mock interface through MockProvider.
- Preserve deterministic output and safe result contract.
- Add tests that live/staging requests cannot receive MockProvider output.

### Phase 3: Enable isolated StagingProvider

Future work:

- Add staging connector registry with non-production endpoints only.
- Convert `integration.n8n_test_bridge` from mock-only to staging-capable test
  bridge behind policy.
- Add durable staging operation logs, callback context, failure handling, and
  result normalization.
- Prove staging cannot access production URLs, credentials, callback hosts, or
  storage namespaces.

### Phase 4: Prepare C15 workflow dispatch path

Future work:

- Keep C15A as registry source of truth.
- Keep C15F whitelist and cross-module block.
- Add staging dispatch adapter after C15A/C15F decision.
- Split hidden webhook refs by env: mock refs, staging refs, live refs.
- Add durable callback/DLQ storage before any non-mock dispatch.

### Phase 5: Enable limited LiveProvider

Future work:

- Start with one low-risk P-series production workflow.
- Require live enrollment for org and module.
- Require live-ready provider contract.
- Require C14 secret resolution and C12 approval where applicable.
- Add rollback, monitoring, idempotency, timeout, retry, audit, and incident
  playbooks before increasing scope.

### Phase 6: Expand live execution by module family

Future work:

- Promote modules from mock -> staging -> live only with evidence.
- Keep module/org policy as the authority.
- Never use mock success as evidence of live readiness.

Upgrade path by category:

| Category | Upgrade path |
|---|---|
| Can upgrade to staging | `integration.n8n_test_bridge`, C15 workflow decision path, payload/result normalization, webhook gateway validation, low-risk K-series sandbox integrations. |
| Can upgrade to live later | Future P-series production workflows after provider router, durable audit/callback/DLQ, C14 secret resolution, C12 approvals, and C18 durable org/module bindings are complete. |
| Must remain mock now | C08 placeholder/product adapters, C09 no-op/mock/contract-only providers, C10 mock sandbox, foundation demo, current n8n test bridge dispatch, C14 AI binding registry, current C15 registry/binding read models. |
| Must rewrite execution layer | C09 provider registry validation, C10 bridge/runtime, C13E no-runtime flags, C15 dispatch/callback/failure persistence, C14 AI/external dependency execution binding, C08 action execution type policy. |

## 10. C08-C15 Execution Path Analysis

This section records the current mock locks that PRE20-D must route around or
replace in later implementation phases.

### C08 Adapters: mock locked

Evidence:

- `docs/C08_MODULE_ADAPTER_BACKEND.md` states C08 does not execute actions,
  connect external providers, or implement execution providers.
- `backend/app/schemas/module_adapter.py` defines adapter execution metadata
  with `execution_type` defaulting to `mock` and live provider flags false.
- `backend/app/services/execution_flow_gate.py` blocks C08 actions whose
  `execution_type` is not `mock` or `no_op`.
- `business.products.placeholder.adapter` and
  `integration.n8n_test_bridge.adapter` are safe shells, not live adapters.

PRE20-D implication:

- C08 should remain a contract surface.
- Future C08 actions must declare allowed provider modes, but must not call
  providers directly.
- Any non-mock C08 action must pass through the router.

### C09 Providers: execution disabled

Evidence:

- `backend/app/core/execution_providers.py` defines `core.no_op_provider`,
  `core.mock_provider`, `core.contract_only_provider`, and disabled future
  providers.
- C09 provider contracts set `executable=False`,
  `can_request_execution=False`, `live_provider_connected=False`,
  `external_endpoint_declared=False`, and `credential_declared=False`.
- `backend/app/services/execution_provider_registry.py` rejects executable
  providers, live connections, external endpoints, callback support, local
  artifact paths, external artifact references, operation-log writes, and audit
  writes in C09B.
- Access state always returns no-execute behavior.

PRE20-D implication:

- C09 must be split into provider metadata registry and runtime provider
  resolver.
- The current validation should remain for contract-only providers but a new
  mode-aware validation path is needed for staging/live readiness.
- Future live provider records need statuses such as `staging_ready` and
  `live_ready`, not `future_live_provider` placeholders.

### C10 Sandbox: mock-only runtime

Evidence:

- `docs/C10_MODULE_SANDBOX_SEAL.md` explicitly seals C10 as disabled execution
  / mock-only.
- `backend/app/sandbox/bridge.py` uses `C09MockExecutionProviderInterface` and
  states no live provider, queue, webhook, callback, or network call is made.
- `backend/app/sandbox/runtime.py` delegates to the C10E mock bridge and
  finalizes disabled-execution mock-only state.
- Runtime response flags include no external provider call, no live provider
  call, no network access, no DB write, and no production/staging mutation.

PRE20-D implication:

- C10 can back MockProvider immediately.
- StagingProvider needs a separate staging sandbox runner or a mode-aware C10
  runtime that is explicitly isolated from the mock path.
- LiveProvider should not reuse mock-only finalization semantics as proof of
  real execution.

### C13 Control Plane: no-runtime gate today

Evidence:

- `backend/app/schemas/execution_flow_gate.py` defines final flow checks but
  hard-codes no external provider call, no runtime execution, no production
  impact, and `external_provider_call_allowed=False`.
- `backend/app/services/execution_flow_gate.py` blocks future provider types,
  executable providers, live provider connections, external endpoints, and
  callback support.
- C13 module switch and kill switch are present as control concepts, but the
  current flow is designed to stop execution leaks, not permit real execution.

PRE20-D implication:

- C13 must become mode-aware before staging/live execution.
- The gate should still default to block, but allowed decisions for staging/live
  need explicit mode, connector, workflow, org, module, and approval evidence.

### C14 AI / External Dependency Binding: contract-only

Evidence:

- `docs/C14X_A_AI_EXECUTION_BINDING_REGISTRY.md` states the registry does not
  execute AI, enter C10 sandbox, or trigger provider calls.
- `backend/app/services/ai_execution_binding_registry.py` validates static
  binding metadata and rejects sensitive runtime markers such as URLs, tokens,
  credentials, provider URLs, and webhook URLs.
- Model locks, capability bindings, dependency rules, and execution prompts are
  routing/validation contracts, not runtime model invocation.

PRE20-D implication:

- C14 remains the dependency and secret policy authority.
- Staging/live providers need C14-approved secret references and connector
  policies.
- AI execution must enter through the router and must never be invoked directly
  by the registry.

### C15 Workflow Execution: no-op / decision-only today

Evidence:

- `docs/C15A_WORKFLOW_REGISTRY_SYSTEM.md` states C15A does not execute n8n
  workflows, trigger AI models, modify staging/production, or expose run APIs.
- `backend/app/services/workflow_registry_system.py` validates hidden n8n refs
  and returns invocation decisions, but does not dispatch.
- `backend/app/services/module_workflow_binding_engine.py` enforces
  `allowed_workflows` and cross-module isolation, then states C15F performs no
  runtime execution.
- `backend/app/services/n8n_test_service.py` records mock/demo execution and
  explicitly blocks external HTTP/webhook dispatch.
- Callback and failure handling stores are currently process-memory, not durable
  staging/live execution infrastructure.

PRE20-D implication:

- C15A/C15F should remain mandatory workflow gates.
- A future C15 dispatch step must call `ExecutionProviderRouter`, not n8n
  directly.
- Staging/live C15 dispatch requires durable callback context, DLQ, replay, and
  result normalization before any real webhook call.

## Upgrade Readiness Matrix

| Layer | Current state | Staging readiness | Live readiness | Required change |
|---|---|---:|---:|---|
| C08 adapters | mock/no-op contracts | low-medium | low | Add mode-aware action policy and router handoff. |
| C09 providers | no-execute registry | low | low | Split contract registry from runtime provider resolver. |
| C10 sandbox | deterministic mock runtime | medium for mock only | low | Add isolated staging runtime; do not reuse mock as live. |
| C13 gate | no-runtime safety gate | low-medium | low | Add mode-aware allowed decisions. |
| C14 AI/deps | static contract registry | medium | low | Add secret refs and connector allowlists by env. |
| C15 workflow | registry/whitelist only | medium | low | Add provider-routed dispatch plus durable callback/DLQ. |
| C17 audit/trace | mixed DB and memory | low-medium | low | Make execution audit/trace/result storage durable. |
| C18 org/module | partial DB + memory binding | low | low | Persist module binding/shared module state before live. |

## Non-Goals For PRE20-D

- No C01-C19 source changes.
- No production requests.
- No live n8n connection.
- No real AI calls.
- No UI work.
- No deployment.

The only PRE20-D deliverable is this provider switch architecture: a unified
mock/staging/live execution abstraction and routing model that future phases can
implement without bypassing the existing permission and control-plane layers.
