# C15B Webhook Gateway

## Scope

C15B defines the unified signed ingress layer for future n8n webhook dispatch.
All workflow requests must enter through the C15B gateway, then be resolved
through the C15A Workflow Registry before n8n can be addressed.

C15B does not expose n8n URLs, does not hardcode webhook addresses, does not
allow direct workflow calls, does not bypass the gateway, does not perform
runtime execution, and does not change staging or production configuration.

## Webhook Gateway Design

Entrypoint:

```text
POST /webhook-gateway/ingress
```

Flow:

```text
requester
  -> C15B Webhook Gateway
  -> C15A Workflow Registry
  -> hidden n8n webhook reference
  -> n8n
```

Rules:

- Every request must enter through C15B.
- C15B looks up workflows through C15A only.
- C15B never returns a real n8n URL or hidden webhook reference.
- Direct n8n paths and direct workflow POST routes are not exposed.
- Current implementation validates and standardizes the request only; runtime
  n8n dispatch remains disabled.

## Signature Verification Model

Header:

```text
X-Barong-Gateway-Signature: sha256=<hex digest>
```

Algorithm:

```text
HMAC-SHA256(canonical JSON payload, webhook_gateway_signing_secret)
```

Signed fields:

```json
{
  "module": "registered module key",
  "workflow_id": "C15A workflow id",
  "context_id": "caller context correlation id",
  "payload": {},
  "timestamp": "ISO-8601 signing timestamp"
}
```

Invalid, missing, or stale signatures are rejected before workflow lookup.
Secrets are never included in responses or logs produced by this gateway model.

## Payload Standardization Format

Canonical gateway payload:

```json
{
  "module": "string",
  "workflow_id": "string",
  "context_id": "string",
  "payload": {},
  "timestamp": "string"
}
```

The schema forbids extra top-level fields. The nested payload must not include
credential keys, direct webhook URL fields, endpoint fields, authorization
fields, or direct n8n reference values.

## Workflow Lookup Flow

1. Validate the C15B signature.
2. Validate the standard payload shape.
3. Ask C15A for the module/workflow decision.
4. Require a registered workflow.
5. Require explicit module binding.
6. Require `active` workflow status.
7. Resolve only the hidden webhook reference internally.
8. Return the gateway decision without exposing n8n address data.

Non-active, unregistered, deprecated, error, and cross-module workflow requests
are rejected.

## API Surface

- `POST /webhook-gateway/ingress`
- `GET /webhook-gateway/design`
- `GET /webhook-gateway/signature-model`
- `GET /webhook-gateway/payload-format`
- `GET /webhook-gateway/workflow-lookup-flow`
- `GET /webhook-gateway/completion-status`

There is no direct `/n8n` route and no direct workflow execution route in C15B.

## Completion Status

C15B is complete:

- Webhook gateway design: complete.
- Signature verification model: complete.
- Invalid request rejection: complete.
- Payload standardization format: complete.
- C15A workflow lookup integration: complete.
- Hardcoded webhook URL: forbidden.
- n8n URL exposure: forbidden.
- Direct workflow call: forbidden.
- Gateway bypass: forbidden.
- Runtime execution: not performed.
- Production/staging changes: not performed.

Can proceed to C15C: yes. C15C can build on the signed C15B gateway boundary
without changing the C15A registry contract or exposing n8n runtime addresses.
