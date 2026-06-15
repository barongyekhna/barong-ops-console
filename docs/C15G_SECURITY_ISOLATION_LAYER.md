# C15G Security & Isolation Layer

日期：2026-06-15 UTC

C15G 构建 n8n Security & Isolation Layer。范围只覆盖隔离、安全清洗和
firewall enforcement；不执行 workflow，不调用 n8n，不调用外部 API，不修改
production/staging，不运行 Docker/pytest，不改变既有业务 API 契约。

## 1. Isolation Architecture

唯一允许路径：

```text
Module
-> C15C Payload Standardization
-> C15F Module Workflow Binding
-> C15B Webhook Gateway
-> C15A Workflow Registry
-> internal hidden webhook resolver
-> n8n
-> C15D Callback Handler
-> C15E Result Normalization
```

隔离规则：

- C15B 是 n8n 的唯一入口。
- module 不接收真实 n8n URL。
- frontend 不代理真实 n8n URL。
- C15A 只保存 opaque hidden ref，不保存真实 webhook address。
- C15B response 不返回 n8n URL，也不返回 hidden ref。
- C15D/C15E 继续拒绝 URL、webhook ref、credential、token 和 authorization data。

## 2. Firewall Rules

Backend explicit deny：

```text
/webhook
/webhook/*
/n8n
/n8n/*
```

Frontend backend proxy deny：

```text
/api/backend/webhook
/api/backend/webhook/*
/api/backend/n8n
/api/backend/n8n/*
/api/backend/webhook-gateway/ingress
encoded http(s) or n8n-webhook-ref bypass segments
```

Nginx template deny：

```text
^/(webhook|n8n)(/|$)
^/api/backend/(webhook|n8n)(/|$)
= /api/backend/webhook-gateway/ingress
```

These rules block direct webhook access, direct n8n access, external bypass
calls, and unauthorized public HTTP paths before they can become execution
routes.

## 3. Webhook Hiding Mechanism

Hiding model：

- Real n8n URL：not stored in frontend or module contracts.
- C15A registry：opaque `n8n-webhook-ref://...` references only.
- C15B：may resolve hidden refs internally only after signature, C15A and C15F
  checks pass.
- Responses：runtime URLs and hidden refs are not returned by C15B/C15D/C15E.
- Logs：operation log details remove runtime address keys and redact runtime
  address values.

Operation log sanitizer blocks:

```text
n8n_webhook
webhook_url
provider_url
endpoint_url
callback_url
target_url
url
endpoint
endpoint_ref
webhook
http://
https://
n8n-webhook-ref://
```

Safe status fields such as `webhook_triggered: false` remain allowed because
they do not disclose an address or credential.

## 4. Gateway Enforcement Model

C15B accept conditions：

```text
valid HMAC signature
+ C15A registered workflow
+ C15A active status
+ C15A module binding
+ C15F module workflow whitelist pass
= gateway accepted
```

Any of these conditions reject before hidden webhook resolution:

- unsigned or stale request
- unregistered workflow
- inactive/deprecated/error workflow
- cross-module workflow call
- workflow not in C15F `allowed_workflows`
- direct `/webhook` or `/n8n` HTTP path
- frontend proxy attempt to access `webhook-gateway/ingress`

The accepted C15B decision still performs no runtime n8n dispatch in this
stage.

## 5. C15G Completion Status

C15G completed:

- isolation architecture implemented.
- firewall rules implemented.
- webhook hiding mechanism implemented.
- gateway enforcement model implemented.
- C15B now requires C15F binding validation before hidden ref resolution.
- direct `/webhook*` and `/n8n*` backend paths blocked.
- frontend backend proxy bypass paths blocked.
- Nginx template deny rules added.
- operation log runtime URL/webhook sanitization added.
- static backend/frontend regression tests added but not executed per safety
  rule.

Safety limits preserved:

- no runtime execution
- no external API call
- no production change
- no staging change
- no Docker
- no pytest
- no git commit

## 6. Readiness For C15H

Can proceed to C15H: YES.

Condition:

- C15H must continue treating C15B as the only n8n entrypoint.
- C15H must not expose real n8n URLs, hidden refs, webhook credentials, or
  callback secrets to frontend/module responses or operation logs.
- C15H must not bypass C15F module workflow binding validation.
