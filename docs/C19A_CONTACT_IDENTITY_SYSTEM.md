# C19A Contact Identity System

## 1. ContactIdentity Schema

`backend/app/schemas/contact_identity.py` defines the immutable communication
identity layer:

```python
class ContactIdentity:
    user_id: str
    name: str
    org_id: str
    org_name: str
    title: str
    role: "owner | org_admin | member"
    immutable_fields: list[str] = ["name", "org_name", "title"]
    created_at: datetime
    updated_at: datetime
```

Identity is separate from authentication. It stores display and organization
snapshot fields for internal communication, not login credentials, passwords,
tokens, sessions, or auth state.

## 2. Immutable Field Enforcement

Only the controlled identity fields can be patched:

```text
allowed patch fields = name, org_name, title
all other fields -> DENY UPDATE
```

`user_id`, `org_id`, `role`, `created_at`, and `updated_at` are not patchable
through the C19A API. `ContactIdentityUpdate` forbids extra request fields and
the service also evaluates requested fields through
`enforce_contact_identity_update`.

## 3. Role-Based Update Rules

Runtime enforcement is implemented in
`backend/app/services/contact_identity_service.py`.

- `owner`: can update controlled identity fields for any user across orgs.
- `org_admin`: can update controlled identity fields only inside the same org.
- `org_admin`: cannot update a target identity whose role is `owner`.
- `member`: cannot update any identity field.

The service derives global owner authority from `users.role == "owner"` and
same-org admin authority from C18C `org_memberships.role == "admin"`.

## 4. Database Schema

Logical table design:

```sql
CREATE TABLE contact_identities (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    org_id TEXT NOT NULL,
    org_name TEXT NOT NULL,
    title TEXT NOT NULL,
    role TEXT CHECK (role IN ('owner', 'org_admin', 'member')) NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

C19A adds a SQLAlchemy model and schema constant only. It does not add or run an
Alembic migration.

## 5. API Design

Implemented backend route design under the existing application API prefix:

- `GET /contacts/{user_id}`
  - Runtime path: `/api/app/contacts/{user_id}`
  - Requires authentication.
  - Owner can read cross-org.
  - Non-owner users must have active same-org C18C membership.

- `PATCH /contacts/{user_id}`
  - Runtime path: `/api/app/contacts/{user_id}`
  - Requires authentication.
  - Accepts only `name`, `org_name`, and `title`.
  - Enforces owner/org_admin/member identity mutation rules.

No UI is implemented.

## 6. C18/C19 Integration

- C18C org membership: contact creation requires active membership in the
  assigned org. Update authority for org admins is derived from same-org active
  membership.
- C18F permission system: C19A uses a service-level permission decision for
  identity mutation because contact routes do not expose frontend-provided
  org/module context.
- C19B global directory: may read `ContactIdentity` snapshots as the directory
  source of truth, but must not mutate identity fields.
- C19C messaging system: may display contact identity snapshots in messages,
  but identity is not chat state and C19A does not implement messaging.

## 7. Security Model

- Identity is not authentication.
- Contact identity rows contain no password, token, session, or credential.
- Creation snapshots `org_name` from the organization at hire time.
- `name`, `org_name`, and `title` are locked by default after creation.
- Ordinary members cannot mutate identity fields, including their own.
- All create/update success and denied update attempts are traceable through
  existing operation logs.
- C17 is not modified.
