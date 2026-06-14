# C14A Secret Rule Definition

日期：2026-06-14 UTC

C14A 定义 Secret Classification System 的分类规则、边界规则和泄漏预防规则。
本阶段只做规则定义，不实现 secret storage，不实现 encryption，不实现 runtime
logic，不新增 API，不接 secrets manager，不修改 production/staging。

## 1. Secret Classification Model

Secret Classification System 只回答一个问题：某类值是否属于 secret，以及该类值
允许停留在哪些系统层。C14A 不保存、读取、解密、加密、轮换或注入任何 secret。

分类模型：

```text
SecretClass
  name
  is_secret
  allowed_access_layers
  forbidden_layers
  frontend_access_allowed
  storage_implementation_status
  runtime_logic_status
```

固定规则：

| 字段 | C14A 固定值 |
| --- | --- |
| `is_secret` | 由本文件的 Secret / Non-Secret 定义决定。 |
| `allowed_access_layers` | 仅允许 backend secure service layer；未来可扩展为 future secrets manager layer。 |
| `forbidden_layers` | C08 module layer、C09 execution layer、C10 sandbox layer、frontend。 |
| `frontend_access_allowed` | 对所有 secret 固定为 `false`。 |
| `storage_implementation_status` | `not_implemented_in_c14a`。 |
| `runtime_logic_status` | `not_implemented_in_c14a`。 |

C14A 的 classification 是静态规则，不是 runtime policy engine。任何后续阶段如果
需要绑定、读取、轮换或审计 secret，必须先引用本分类模型并在新的任务中单独设计。

## 2. Secret vs Non-Secret Definition

以下类型必须标记为 secret：

| Type | Classification | 说明 |
| --- | --- | --- |
| `API_KEY` | secret | 任何外部或内部 API key，包括 provider key、service key、webhook key。 |
| `ACCESS_TOKEN` | secret | Bearer token、session-like token、OAuth token、service access token。 |
| `DB_PASSWORD` | secret | 数据库密码、连接凭据中的 password 部分。 |
| `JWT_SECRET` | secret | JWT signing / verification secret。 |
| `THIRD_PARTY_CREDENTIALS` | secret | 第三方 provider credential、client secret、callback secret、integration credential。 |

以下类型明确不是 secret：

| Type | Classification | 说明 |
| --- | --- | --- |
| `module_key` | non-secret | 模块稳定标识，只能作为 routing / registry metadata。 |
| `action_key` | non-secret | adapter action 稳定标识，只能作为 action contract metadata。 |
| `execution_id` | non-secret | execution contract identifier；不得编码 secret 或 provider value。 |
| `approval_id` | non-secret | approval workflow identifier；不得编码 secret 或 reviewer credential。 |
| `logs (non-sensitive)` | non-secret | 已脱敏、无 credential、无 raw payload、无 secret-shaped value 的日志摘要。 |

Non-secret 类型只表示该字段本身不是 secret。若这些字段被拼接、编码或污染为包含
secret material 的值，则该值整体按 secret 处理并禁止进入公开响应、日志、frontend、
C08、C09 或 C10。

## 3. System Boundary Rules

Secret flow rules：

```text
secret -> C08 module layer      FORBIDDEN
secret -> C09 execution layer   FORBIDDEN
secret -> C10 sandbox layer     FORBIDDEN
secret -> frontend              FORBIDDEN
```

Layer boundary：

| Layer | Secret access | C14A rule |
| --- | --- | --- |
| C08 Module Adapter / module layer | forbidden | Adapter contract may declare future secret requirement only; it must not include secret value, credential, token, URL with credential, or env value. |
| C09 Execution Provider / execution layer | forbidden | Execution request/result/state may carry `secret_binding_status` only; it must not carry secret values or provider credentials. |
| C10 Sandbox / sandbox layer | forbidden | Sandbox request/context/runtime must remain no-secret and mock-only; no secret injection into sandbox payloads. |
| Frontend | forbidden | Browser code, local storage, UI props, API responses, route payloads and logs must never receive backend/provider secrets. |
| Backend secure service layer | allowed by rule only | The only current allowed layer for future secret handling; C14A does not implement it. |
| Future secrets manager layer | future allowed | Reserved future boundary for secret storage/binding/rotation/audit; not implemented in C14A. |

C14A preserves the existing sealed flow:

```text
C08 -> C13 -> C12 -> C09 -> C10
```

Secrets do not travel through that flow. The flow may carry only safe metadata such as
`requires_secret=true`, `secret_binding_status=secret_rules_required`, or safe block
reasons.

## 4. Leakage Prevention Rules

Mandatory leakage prevention rules：

- Public API responses must not include secret values, secret-shaped fields, provider
  credentials, Authorization headers, raw env values, provider URLs with credentials,
  webhook secrets, or token material.
- Frontend may display only safe status labels such as `secret_required`,
  `secret_rules_required`, `waiting for C14 Secret Rules`, or safe missing-state
  summaries.
- C08 adapter contracts may declare a future secret requirement, but must not expose
  secret names that reveal real provider credentials or any secret value.
- C09 execution contracts may declare `secret_binding_status`, but must not serialize
  secret material into `input_payload`, `sanitized_input_summary`, `result_summary`,
  `artifact_refs`, `error_message_safe`, or operation-log references.
- C10 sandbox contracts must reject or block any request that indicates secret binding
  has not been cleared; C14A does not authorize secret injection into sandbox runtime.
- Logs are non-secret only after sanitization. Raw logs, raw provider errors, raw
  request payloads, stack traces containing env/config values, and credential-shaped
  strings are secret-contaminated and must not be displayed or persisted as normal logs.
- Identifiers such as `module_key`, `action_key`, `execution_id`, and `approval_id`
  must remain opaque/safe identifiers and must not be generated from, include, hash, or
  encode secret values.
- Any boundary ambiguity is fail-closed: treat the value as secret and keep it out of
  C08, C09, C10, frontend, public API responses and non-sensitive logs.

## 5. Allowed Access Layers

Allowed layers:

```text
backend secure service layer only
future secrets manager layer
```

C14A does not define how either layer stores, encrypts, decrypts, rotates, fetches or
injects secrets. It only defines that all other layers are forbidden.

Not allowed in C14A:

- secret storage implementation
- encryption implementation
- runtime secret read/write logic
- API integration
- frontend access
- C08/C09/C10 secret propagation
- production/staging configuration changes

## 6. Safety Rules

C14A safety rules are mandatory:

- no secret storage implementation
- no encryption implementation
- no runtime logic
- no API integration
- no production changes
- no staging changes
- no backend runtime code change
- no frontend runtime code change
- no migration
- no docker
- no pytest
- no runtime execution
- no git commit

This document may be used by C14B as a prerequisite, but it does not itself activate any
secret access path.

## 7. C14A Completion Status

C14A completed:

- Secret classification model defined.
- Required secret types classified: `API_KEY`, `ACCESS_TOKEN`, `DB_PASSWORD`,
  `JWT_SECRET`, `THIRD_PARTY_CREDENTIALS`.
- Required non-secret types classified: `module_key`, `action_key`, `execution_id`,
  `approval_id`, `logs (non-sensitive)`.
- System boundary rules defined: secrets cannot enter C08 module layer, C09 execution
  layer, C10 sandbox layer, or frontend.
- Allowed access layers fixed as backend secure service layer only and future secrets
  manager layer.
- Leakage prevention rules defined.
- C14A safety limits preserved: no storage, no encryption, no runtime logic, no API
  integration, no production/staging changes.

C14A completion status: complete.

Can proceed to C14B: YES, if C14B remains a separately approved task and does not treat
C14A as authorization to implement storage, encryption, runtime secret reads, frontend
secret access, or production/staging changes.
