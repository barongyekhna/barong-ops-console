# C18B Organization Lifecycle

C18B adds executable lifecycle control for Organization records. It builds on
the C18A organization schema and keeps the scope limited to create, update,
soft delete, activate, and suspend.

## 1. State Machine

Organization statuses:

- `active`: normal access.
- `suspended`: access paused; data retained.
- `deleted`: logical deletion; terminal state.

Allowed transitions:

- `active -> suspended`
- `suspended -> active`
- `active -> deleted`
- `suspended -> deleted`

Idempotent transitions:

- `active -> active`
- `suspended -> suspended`

Forbidden transitions:

- `deleted -> active`
- `deleted -> suspended`
- `deleted -> deleted`
- Any lifecycle transition where `actor_user_id != owner_user_id`

`deleted` is terminal. No API restores a deleted organization.

## 2. API Design

Implemented router: `backend/app/api/org.py`.

Runtime prefix: `/api/app`.

Contract endpoints:

- `POST /org/create`
  - Creates an organization.
  - Generates `org_id` internally.
  - Sets `status=active`.
  - Requires `current_user.id == payload.owner_user_id`.

- `PATCH /org/{org_id}`
  - Updates `org_name`, `org_type`, and `metadata` only.
  - Rejects `org_id`, `owner_user_id`, and `status` mutation.
  - Requires `current_user.id == organization.owner_user_id`.
  - Does not change lifecycle status.

- `DELETE /org/{org_id}`
  - Soft deletes only.
  - Sets `status=deleted`.
  - Requires `current_user.id == organization.owner_user_id`.
  - Never physically deletes the row.

- `POST /org/{org_id}/activate`
  - Sets `status=active`.
  - Allowed from `active` and `suspended`.
  - Forbidden from `deleted`.
  - Requires `current_user.id == organization.owner_user_id`.

- `POST /org/{org_id}/suspend`
  - Sets `status=suspended`.
  - Allowed from `active` and `suspended`.
  - Forbidden from `deleted`.
  - Requires `current_user.id == organization.owner_user_id`.

## 3. Owner-Only Enforcement

The lifecycle boundary is identity based, not role based:

```text
if actor_user_id != owner_user_id:
    deny lifecycle operation
```

This rule applies to create, update, delete, suspend, and activate. C18B does
not grant lifecycle authority through `owner`, `admin`, `super_admin`,
`module_admin`, or any future permission role.

Create uses the requested `payload.owner_user_id` as the owner check target.
Existing-organization operations load the row by `org_id` and compare the
current authenticated user id to the stored `owner_user_id`.

## 4. Status Transition Rules

Transition validation is defined in
`backend/app/schemas/organization.py::evaluate_organization_status_transition`.

Rules:

- `delete` may transition `active` or `suspended` to `deleted`.
- `suspend` may transition `active` to `suspended`.
- `activate` may transition `suspended` to `active`.
- Repeated `activate` on `active` and repeated `suspend` on `suspended` are
  idempotent.
- Any operation from `deleted` is rejected with conflict semantics.
- `PATCH /org/{org_id}` cannot change status.

## 5. Soft Delete Strategy

Delete is implemented as a status update:

```text
organizations.status = "deleted"
```

There is no physical delete path in the repository or service layer. Deleted
rows remain available for audit, future retention policy, and future C18 data
governance work.

C18B does not create or execute database migrations. It expects the
`organizations` table contract declared by C18A:

- `org_id`
- `org_name`
- `org_type`
- `owner_user_id`
- `status`
- `metadata`
- `created_at`
- `updated_at`

## 6. Security Boundary

Lifecycle operations are bound to an explicit `org_id` except create, where
the generated `org_id` is returned after owner validation.

Security properties:

- Authentication is required through the existing session dependency.
- Owner-only control is enforced inside the service layer.
- Non-owner attempts return `403`.
- Missing organizations return `404`.
- Illegal terminal-state transitions return `409`.
- Success and failure attempts write operation logs with action names
  `org.create`, `org.update`, `org.delete`, `org.activate`, and `org.suspend`.
- C18B uses existing operation-log infrastructure only; it does not modify the
  C17 audit system.
- No UI, module binding, permission-system expansion, or cross-org query is
  implemented.

## 7. Integration Notes For C18C-C18H

- C18C can attach richer organization structure to the same `org_id` identity
  without changing lifecycle ownership rules.
- C18D module binding must treat `deleted` organizations as inaccessible and
  must not create bindings for suspended or deleted organizations unless a
  later contract explicitly allows it.
- C18E permission work must not override C18B owner-only lifecycle control.
  Permissions may govern resource access, not organization lifecycle authority,
  unless a later approved owner-delegation phase changes the model.
- C18F data isolation should use `org_id` as the partition key and reject
  cross-org defaults.
- C18G access-control checks should reuse `owner_user_id` and `status` as
  mandatory lifecycle gates before data access.
- C18H reporting/audit views can read operation-log actions emitted by C18B,
  but C18B does not add a dashboard or C17 storage changes.
