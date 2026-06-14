# C14B Secret Storage Policy

日期：2026-06-14 UTC

C14B 在 C14A Secret Classification Rules 的基础上定义 Secret Storage Policy
（密钥存储规则体系）。本阶段只定义存储位置、访问边界、加密要求和运行时限制；
不实现 secret storage，不接真实 vault，不实现 encryption runtime，不读取真实
secret，不修改 production/staging。

## 1. Secret Storage Model

C14B 的 Secret Storage Policy 只回答三个问题：

- secret 可以被放在哪类受控存储位置。
- 哪些系统层可以解析 secret。
- secret 在存储、日志、执行上下文和 sandbox 边界中必须如何被隔离。

Secret storage model:

```text
SecretStoragePolicy
  storage_location
  storage_status
  encrypted_at_rest_required
  access_layer
  forbidden_layers
  runtime_resolution_rule
  logging_policy
  execution_snapshot_policy
```

固定规则：

| 字段 | C14B 固定值 |
| --- | --- |
| `storage_location` | environment variables、secure vault、encrypted storage。 |
| `storage_status` | `policy_defined_only`，C14B 不创建或接入真实存储。 |
| `encrypted_at_rest_required` | `true`。 |
| `access_layer` | backend secure service layer only。 |
| `forbidden_layers` | frontend、C08 module layer、C09 execution layer、C10 sandbox layer。 |
| `runtime_resolution_rule` | only controlled backend service layer can resolve secrets。 |
| `logging_policy` | secret values must not be logged。 |
| `execution_snapshot_policy` | secret values must not appear in execution context snapshot。 |

C14B 不改变 C14A 的 secret classification。任何值只要被 C14A 判定为 secret，
就必须遵守本文件的存储与访问规则。

## 2. Storage Locations

C14B 定义三类允许的 secret storage locations。它们是 policy locations，不表示本
阶段已经实现或连接对应后端。

| Location | C14B status | Policy |
| --- | --- | --- |
| environment variables (`.env`) | allowed as deployment-time source only | 仅允许作为后端部署时注入的 secret source；若落成文件或部署工件，必须满足 at-rest 加密/受控保护；不得提交真实 `.env`，不得传给 frontend、C08、C09 或 C10。 |
| secure vault | conceptual only | 预留未来 vault / secrets manager 边界；C14B 不接 Vault、云 KMS、云 Secret Manager 或任何真实外部服务。 |
| encrypted storage | conceptual only | 预留未来数据库或文件级 encrypted storage；C14B 不创建表、不写 migration、不实现加解密代码。 |

Storage location rules:

- Secret values may exist only inside approved backend secret sources and the
  backend secure service layer resolution boundary.
- Environment variables are a source, not a transport mechanism. They must not
  be copied into API responses, frontend config, module contracts, execution
  payloads, sandbox requests, operation logs, or context snapshots.
- Secure vault and encrypted storage are future conceptual locations. C14B
  defines required behavior but does not integrate any concrete provider.
- Any file, table, API payload, cache, or context object not explicitly covered
  by this policy is treated as not approved for secret storage.

## 3. Storage Rules

Secrets must NOT be stored in:

```text
frontend                  FORBIDDEN
C08 module layer          FORBIDDEN
C09 execution layer       FORBIDDEN
C10 sandbox layer         FORBIDDEN
```

Forbidden storage examples:

| Layer | Forbidden secret storage |
| --- | --- |
| Frontend | browser bundle, React props/state, local/session storage, cookies created by frontend code, frontend logs, route payloads, frontend tests or fixtures containing real secrets. |
| C08 module layer | module manifests, adapter contracts, action definitions, dependency declarations, module registry records, adapter fixtures. |
| C09 execution layer | execution request/result/state contracts, provider registry output, `input_payload`, `sanitized_input_summary`, `result_summary`, `artifact_refs`, provider access state. |
| C10 sandbox layer | sandbox request, execution context, runtime snapshot, sandbox env injection, bridge payload, runner logs, mock sandbox fixtures. |

Allowed storage is limited to backend-controlled secret sources and future
secret manager boundaries. C14B does not make those locations executable or
available to downstream layers.

## 4. Access Control Rules

Access policy:

```text
backend secure service layer only access
no cross-module secret access
no frontend exposure
```

Mandatory access rules:

- Only a controlled backend secure service layer may resolve secret values.
- Frontend must never receive raw secrets, masked secrets that can be reversed,
  provider credentials, Authorization headers, token material, callback
  secrets, provider URLs with embedded credentials, or raw env values.
- C08 may declare that an action requires a future secret, but it must not
  know, store, request, or serialize the secret value.
- C09 may carry safe secret metadata such as `requires_secret` or
  `secret_binding_status`, but it must not directly access, resolve, store, or
  serialize the secret value.
- C10 must receive only non-secret execution context. It must not receive raw
  secrets, derived credentials, env values, provider tokens, or secret-bearing
  snapshots.
- A module must not access another module's secret binding. Secret resolution,
  when later implemented, must be scoped by module/action/provider ownership and
  fail closed on mismatch.
- Any request for secret access outside the controlled backend service layer is
  denied by policy.

## 5. Encryption Policy

Encryption policy:

```text
secret encrypted at rest: REQUIRED
secret logging: FORBIDDEN
secret in execution context snapshot: FORBIDDEN
```

Mandatory encryption and leakage rules:

- Secrets must be encrypted at rest in any future durable storage.
- Environment variable backed secrets must be protected by deployment/runtime
  environment controls. If materialized as a `.env` file or deployment artifact,
  they must be encrypted or equivalently protected at rest, and must not be
  written into normal application storage.
- Future secure vault or encrypted storage integration must keep encryption,
  key management, access audit, and rotation inside backend secure boundaries.
- Raw secret values must not be logged in application logs, operation logs,
  audit events, frontend console output, provider errors, test fixtures, stack
  traces, sandbox logs, or execution summaries.
- Secret values must not appear in execution context snapshots, sandbox
  snapshots, approval context snapshots, result snapshots, artifact metadata,
  memory events, or review records.
- Masking is not a storage permission. A masked value may be displayed only
  when it cannot be reversed and does not reveal enough material to authenticate
  with a provider.
- Any secret-shaped value found in logs, snapshots, payloads, fixtures, or
  frontend output is treated as leakage and must fail closed.

## 6. Runtime Access Rules

Runtime restrictions:

```text
C09 execution CANNOT directly access secrets
C10 sandbox MUST NOT receive raw secrets
only controlled backend service layer can resolve secrets
```

Detailed runtime rules:

- C09 execution providers cannot directly read `.env`, vault, encrypted
  storage, provider credentials, callback secrets, or access tokens.
- C09 request/result/state contracts can include only safe metadata:
  `requires_secret`, `secret_binding_status`, safe missing-state reasons, or
  future binding identifiers that do not reveal secret values.
- C10 sandbox must not receive raw secrets through request payloads, environment
  variables, mounted files, execution context snapshots, bridge payloads, test
  fixtures, or runner configuration.
- Backend secure service resolution, when later implemented, must happen before
  any provider operation and must return only the minimum derived capability
  needed by a controlled backend service. It must not pass raw secret material
  into C08, C09, C10, or frontend.
- Runtime secret access is not activated by C14B. Secret-bearing providers
  remain non-executable unless a later approved phase defines binding,
  resolution, provider invocation, audit, rotation, and verification.

## 7. Safety Rules

C14B safety rules are mandatory:

- no runtime execution
- no real vault integration
- no encrypted storage implementation
- no secret read/write runtime
- no production changes
- no staging changes
- no Docker run
- no pytest
- no backend runtime code change
- no frontend runtime code change
- no migration
- no API integration
- no real `.env` creation or modification
- no git commit

C14B is a policy layer. It does not unlock C09 execution, does not inject
secrets into C10 sandbox, does not expose secrets to frontend, and does not
authorize any provider live call.

## 8. C14B Completion Status

C14B completed:

- Secret storage model defined.
- Storage locations defined: environment variables (`.env`), secure vault
  conceptual boundary, encrypted storage conceptual boundary.
- Storage rules defined: secrets must not be stored in frontend, C08 module
  layer, C09 execution layer, or C10 sandbox layer.
- Access control rules defined: backend secure service layer only, no
  cross-module secret access, no frontend exposure.
- Encryption policy defined: secrets encrypted at rest, never logged, never
  present in execution context snapshots.
- Runtime restrictions defined: C09 cannot directly access secrets, C10 must not
  receive raw secrets, only controlled backend service layer can resolve
  secrets.
- C14B safety limits preserved: no runtime execution, no real vault
  integration, no production/staging changes, no Docker, no pytest, no git
  commit.

C14B completion status: complete.

Can proceed to C14C: YES, if C14C remains a separately approved task and does
not treat C14B as authorization to implement live provider execution, frontend
secret exposure, C09 direct secret reads, C10 raw secret injection, production
changes, staging changes, or unreviewed vault/encrypted-storage integration.
