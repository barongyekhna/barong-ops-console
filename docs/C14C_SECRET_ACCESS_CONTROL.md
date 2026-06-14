# C14C Secret Access Control

日期：2026-06-14 UTC

C14C 在 C14A Secret Classification Rules 和 C14B Secret Storage Policy 的基础上
定义 Secret Access Control Layer（密钥访问控制层）。本阶段只定义访问主体、访问条件、
访问层级、模块隔离、运行时限制和 enforcement model；不实现 runtime secret access，
不接真实 vault，不新增 API，不修改 backend/frontend runtime，不修改 production/staging。

## 1. Secret Access Model

C14C 的 Secret Access Control Layer 只回答三个问题：

- who can access secrets
- under what conditions
- at what layer

Secret access policy model:

```text
SecretAccessPolicy
  subject_type
  subject_role
  subject_id
  module_scope
  action_scope
  secret_class
  secret_binding_ref
  requested_operation
  requested_layer
  access_condition
  decision
  denial_reason
  audit_event_status
```

固定规则：

| 字段 | C14C 固定值 |
| --- | --- |
| `subject_type` | `owner`、`admin`、`system`、`service_layer`、`user_frontend`。 |
| `subject_role` | 绑定 C04/C05 role 与 permission 结果；`admin` 是被显式授权的管理主体，不是新的系统 role。 |
| `module_scope` | 必须显式绑定 owning module；没有 module scope 时不能读取 module secret。 |
| `action_scope` | 必须显式绑定 allowed action/provider purpose；不能用模块权限泛化成所有 secret 权限。 |
| `secret_class` | 必须引用 C14A secret classification。 |
| `secret_binding_ref` | 只能是未来安全引用，不得包含 secret value、token、password、credential 或 provider URL。 |
| `requested_operation` | `metadata_read`、`binding_manage`、`resolve_for_backend_service`、`rotate`、`audit_read`；默认不允许 raw value export。 |
| `requested_layer` | 只有 backend secure service layer 可以解析 secret；frontend、C08、C09、C10 禁止。 |
| `access_condition` | authenticated + authorized + scoped + layer-allowed + purpose-bound + auditable。 |
| `decision` | deny by default；explicit allow only。 |
| `audit_event_status` | conceptual only；C14C 不新增 audit storage 或 runtime logging。 |

Access model:

```text
request secret access
  -> classify value by C14A
  -> validate storage boundary by C14B
  -> validate subject role and permission
  -> validate module/action/provider scope
  -> validate requested layer
  -> validate runtime path
  -> allow only backend secure service resolution
  -> emit conceptual audit event
```

任何一步不满足，结果都是 `DENY`。C14C 不创建可执行 policy engine；这些规则是后续实现
secret binding、resolution、rotation、audit 前必须遵守的访问控制合同。

## 2. Role-based Control Rules

Role-based access control:

| Subject | Access level | Allowed operations | Conditions | Forbidden |
| --- | --- | --- | --- | --- |
| `owner` | full policy and management access | `metadata_read`、`binding_manage`、`rotate`、`audit_read`、authorize backend service resolution | 必须是 authenticated owner；必须通过 backend secure service layer；必须保留 module/action scope 和 conceptual audit boundary。 | 不得把 raw secret 返回 frontend、C08、C09、C10、public API response、logs 或 snapshots。 |
| `admin` | limited access | scoped `metadata_read`、scoped `binding_manage`、scoped `audit_read`；未来可由 owner 授权 rotate | 必须有显式 permission assignment，例如未来 `secrets.manage` 或 module-scoped secret permission；必须绑定 module/action/provider scope。 | 不能 owner-equivalent；不能跨模块；不能 raw export；不能绕过 C05/C06 permission enforcement。 |
| `system` | internal access only | backend internal `resolve_for_backend_service` and safe status update | 必须是受控 backend internal process；必须由已授权 module/action/provider purpose 触发；必须最小化能力。 | 不能作为 human/user/frontend subject；不能通过 browser/API 直接请求 secret；不能写入 logs/snapshots。 |
| `service_layer` | controlled access | `resolve_for_backend_service` only | 仅限 backend secure service layer；必须按 module/action/provider 绑定；只返回后端服务完成动作所需的最小派生能力。 | 不能向 C08、C09、C10 或 frontend 传 raw secret；不能保存到 execution context。 |
| `user_frontend` | no access | safe `metadata_read` status only, if backend has already sanitized it | 只能接收非 secret 状态，例如 `secret_required`、`secret_rules_required`、`not_configured`、`configured`。 | 不能接收 raw secret、masked reversible secret、credential、Authorization header、env value、provider URL with credential。 |

Important role clarifications:

- `owner -> full access` means full secret governance and backend-secure management authority.
  It is not an exception to the no-frontend-secret rule.
- `admin -> limited access` covers future `super_admin`、`module_admin` 或被 C05/C06 显式授予
  secret permission 的管理主体。角色名本身不自动授予 secret access。
- `system -> internal access only` cannot be used to hide a human initiated raw-secret read.
  The request must remain purpose-bound and auditable.
- `service layer -> controlled access` is a layer capability, not a human permission. It must
  always be called on behalf of an authorized module/action/provider purpose.
- `user/frontend -> NO access` includes browser runtime, React props/state, local/session
  storage, frontend API proxy payloads, UI logs and frontend tests containing real secrets.

## 3. Module Isolation Rules

Module isolation rule:

```text
module A cannot read module B secrets
no cross-module secret sharing
strict boundary enforcement
```

Secret binding scope must be modeled as:

```text
SecretBindingScope
  owning_module_key
  allowed_action_keys
  provider_key
  environment_scope
  owner_or_admin_scope
  lifecycle_state
```

Mandatory isolation rules:

- Every secret binding must have exactly one `owning_module_key`.
- A module may access only secret bindings whose `owning_module_key` equals the requesting
  module key.
- A module may resolve a secret only for an explicitly allowed action/provider purpose.
- Module registry metadata, adapter contracts, execution provider contracts and sandbox
  requests may carry only safe references/status; they must not carry secret values.
- Secret references must not be reusable across modules unless a later separately approved
  shared-secret policy defines ownership, approval, audit, rotation, blast-radius and
  revocation semantics.
- Copying a secret binding reference from module A into module B is forbidden unless the
  backend secure service layer rejects the mismatch by policy.
- `module_key`、`action_key`、`execution_id`、`approval_id` and log IDs must not encode,
  hash, derive from, or reveal secret values.
- Any module-bound secret access request with missing, ambiguous or mismatched module scope
  must fail closed.

Cross-module examples:

| Case | C14C decision | Reason |
| --- | --- | --- |
| `business.products` requests its own provider secret for an allowed backend service action | conditional allow | Only if owner/admin/system/service-layer checks pass and resolution stays in backend secure layer. |
| `business.products` requests `integration.n8n_test_bridge` secret | deny | Cross-module access. |
| C08 adapter declares `requires_secret=true` without a value | allow as safe metadata | No secret material crosses into C08. |
| C09 execution payload contains a provider token | deny | C09 cannot directly access or carry secrets. |
| C10 sandbox receives env value or token | deny | C10 must remain no-secret. |

## 4. Runtime Access Rules

Runtime restrictions:

```text
C09 execution CANNOT directly access secrets
C10 sandbox MUST NOT receive secrets
secrets only resolved in backend secure layer
```

Detailed runtime rules:

- C09 execution providers cannot read `.env`, vault, encrypted storage, provider credentials,
  access tokens, callback secrets or generated secret bindings.
- C09 contracts may carry only safe metadata: `requires_secret`, `secret_binding_status`,
  `secret_rules_required`, safe block reasons or future opaque binding references that do not
  reveal values.
- C09 request/result/state must not contain raw secret material in `input_payload`,
  `sanitized_input_summary`, `result_summary`, `artifact_refs`, `error_message_safe`,
  provider state or operation-log references.
- C10 sandbox must not receive secrets through payloads, env injection, mounted files,
  execution context snapshots, bridge payloads, runner config, mock fixtures or logs.
- Backend secure service resolution, when later implemented, must happen before provider
  operation and must not pass raw secret material into C08, C09, C10 or frontend.
- If a future backend service needs a provider credential to perform a controlled action, the
  resolution result must be the minimum capability needed for that backend service call and
  must not be serialized into downstream contracts.
- Runtime secret access is not activated by C14C. Secret-required providers remain blocked
  unless a later approved phase defines executable binding, resolution, audit and verification.

Layer access matrix:

| Layer | Raw secret access | Safe metadata | C14C rule |
| --- | --- | --- | --- |
| Backend secure service layer | conditional allow | allow | Only explicit role/scope/purpose allow can resolve secrets. |
| Future secrets manager layer | future conditional allow | allow | Conceptual boundary only; no integration in C14C. |
| C08 module adapter layer | deny | allow | Can declare requirement/status only. |
| C09 execution layer | deny | allow | Cannot directly access or carry secrets. |
| C10 sandbox layer | deny | limited safe status only | Must not receive secret values or secret-derived credentials. |
| Frontend/user layer | deny | sanitized status only | No raw, reversible masked or credential-bearing value. |

## 5. Access Enforcement Model

Enforcement principles:

```text
deny by default
explicit allow only
audit logging conceptual only
```

Mandatory enforcement rules:

- Deny by default: if no policy explicitly allows the exact subject + operation + module +
  action + provider + layer combination, deny.
- Explicit allow only: role alone is insufficient except owner full governance authority, and
  owner access still must stay inside backend secure boundaries.
- Least privilege: allow only the minimum operation required for the requested purpose.
- Scope binding: module, action, provider and environment scope must all match before
  resolution can be allowed.
- Layer validation: requests from frontend, C08, C09 and C10 are denied for raw secret access
  regardless of role.
- No raw export: secret values must not be downloaded, displayed, logged, snapshotted,
  serialized or returned in public API responses.
- Fail closed: missing scope, unknown role, unknown module, ambiguous action, invalid layer,
  unclassified value or secret-shaped data in a non-secret field must deny.
- Conceptual audit logging: every future allow/deny decision should record actor, role,
  module, action, provider, operation, decision, reason, timestamp and request trace ID, while
  excluding raw secret values, reversible masks, credentials, Authorization headers and raw env.
- Separation of concerns: classification belongs to C14A, storage belongs to C14B, access
  control belongs to C14C. None of these documents by itself enables runtime provider execution.

Conceptual policy decision:

```text
ALLOW only if:
  subject is authenticated or verified internal system subject
  subject role is allowed for requested operation
  permission/scope is explicit where required
  module scope matches the secret binding owner
  action/provider purpose matches the binding scope
  requested layer is backend secure service layer
  requested operation does not export raw secret to forbidden layers
  decision can be audited without logging the secret

Otherwise:
  DENY
```

## 6. Safety Rules

C14C safety rules are mandatory:

- no runtime execution
- no vault integration
- no secret storage implementation
- no encryption implementation
- no secret read/write runtime
- no backend runtime code change
- no frontend runtime code change
- no API integration
- no migration
- no production changes
- no staging changes
- no real `.env` creation or modification
- no Docker run
- no pytest
- no git commit

C14C is an access-control policy layer. It does not unlock C09 execution, does not inject
secrets into C10 sandbox, does not expose secrets to frontend, does not connect a vault and
does not authorize any live provider call.

## 7. C14C Completion Status

C14C completed:

- Secret access model defined: subject, role, module/action scope, requested operation,
  requested layer, condition, decision and conceptual audit status.
- Role-based control rules defined:
  - owner has full policy and management access inside backend secure boundaries.
  - admin has limited, explicit, scoped access only.
  - system has internal access only.
  - service layer has controlled backend secure resolution access only.
  - user/frontend has no raw secret access.
- Module isolation rules defined: module A cannot read module B secrets, no cross-module
  secret sharing, strict module/action/provider boundary enforcement.
- Runtime restrictions defined: C09 execution cannot directly access secrets, C10 sandbox
  must not receive secrets, secrets are resolved only in backend secure layer.
- Enforcement strategy defined: deny by default, explicit allow only, least privilege,
  fail closed, conceptual audit logging only.
- C14C safety limits preserved: no runtime execution, no vault integration, no
  production/staging changes, no Docker, no pytest, no git commit.

C14C completion status: complete.

Can proceed to C14D: YES, if C14D remains a separately approved task and does not treat C14C
as authorization to implement live provider execution, C09 direct secret access, C10 secret
injection, frontend secret exposure, production/staging changes, unreviewed vault integration
or runtime secret read/write paths.
