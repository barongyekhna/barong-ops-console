# C19E Cross-Org Communication Layer

## 1. CrossOrgPolicy

`backend/app/schemas/cross_org_communication.py` defines:

```python
CrossOrgPolicy = {
    "mode": "open | restricted | closed",
    "rules": {
        "allow_cross_org_chat": True,
        "require_permission": True,
        "require_mutual_approval": False,
    },
}
```

Current default:

- `mode = "open"`
- cross-org chat is allowed
- C18F permission is mandatory for cross-org communication
- mutual approval is reserved and disabled

## 2. Permission Logic

`backend/app/services/cross_org_communication.py` exposes:

```python
can_communicate(db, payload, actor, audit=None)
```

Decision order:

1. Authenticated `actor.id` must equal `sender_user_id`.
2. C19A contact identity must resolve both users.
3. C18C active org membership must exist for both users.
4. Same org users are allowed after identity and membership validation.
5. Cross-org users require C19E policy allow plus C18F permission.
6. C18F checks module `C19E`, action `read`, scoped to the sender org.
7. Deny if C18F, policy, identity, or membership checks fail.

## 3. Conversation Rules

C19D direct conversations may cross organizations. C19E does not modify the
C19D schema; instead it returns a C19E envelope:

```json
{
  "conversation_cross_org_field": "conversation.cross_org",
  "conversation_cross_org_value": true
}
```

When sender and receiver orgs differ, C19E marks the conversation as cross-org
in the response boundary.

## 4. Message Flow Rules

`POST /messages/send` now runs C19E before accepting the message into the send
boundary.

The response envelope records:

- `sender_org_id`
- `receiver_org_id`
- `cross_org`
- C18G scoped flag
- C17 trace flag

No message persistence, websocket, file/image/voice/video, or group chat logic is
implemented in C19E.

## 5. API Design

Application routes:

- `POST /comm/cross-org/check`
- `POST /messages/send`

Both routes are internal application APIs under `/api/app`. No public or
control-plane API is exposed for cross-org messaging.

## 6. Security Boundaries

C19E enforces:

- no org bypass
- sender must match authenticated actor
- all cross-org communication must pass C18F
- data scope remains governed by C18G
- cross-org behavior is logged through C17 event collection
- C19A identity and C18C active membership are required

Same-org communication follows the explicit C19E rule:

```text
sender.org_id == receiver.org_id -> ALLOW
```

Cross-org communication follows:

```text
sender.org_id != receiver.org_id
  -> C19E policy
  -> C18F permission
  -> C18G-scoped message envelope
  -> C17 trace event
```

## 7. Integration

- C18C: `org_memberships` active membership verification
- C18F: `permission_isolation.check_permission()`
- C18G: org-scoped API/session boundary and message envelope scope
- C19A: `contact_identities` identity verification
- C19D: direct conversation lookup and participant binding
- C17: `event_collector.emit_event()` for check/send traces

## 8. System Behavior Diagram

```text
POST /messages/send or /comm/cross-org/check
  -> authenticated internal user
  -> sender_user_id must match authenticated actor
  -> C19A resolves sender and receiver contact identities
  -> C18C verifies both users have active org memberships
  -> if sender.org_id == receiver.org_id: allow same-org communication
  -> if orgs differ:
       -> apply CrossOrgPolicy(mode=open by default)
       -> require C18F check on module C19E/action read in sender org
       -> deny when C18F, policy, or identity checks fail
  -> C19D conversation remains direct and is marked conversation.cross_org=True
     in the C19E envelope when participant orgs differ
  -> message envelope records sender_org_id and receiver_org_id
  -> C18G keeps data scoped by org ids; cross-org data access is never granted
  -> C17 event trace records allow/deny and cross_org behavior
```
