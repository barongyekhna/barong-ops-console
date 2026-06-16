# C18F Permission Isolation Layer

## 1. Permission Data Model

`backend/app/schemas/permission.py` defines the runtime permission shape:

```python
Permission = {
    "user_id": "string",
    "org_id": "string",
    "module_id": "string",
    "actions": ["read", "write", "delete", "execute", "admin"],
    "role": "owner | admin | member",
}
```

This model is a runtime authorization contract only. It does not add storage,
does not change existing permission tables, and does not grant data access.

## 2. check_permission()

`backend/app/services/permission_isolation.py` exposes:

```python
check_permission(db, user_id, org_id, module_id, action)
```

Decision order:

1. If `users.role == "owner"`, allow immediately.
2. If the user does not have active C18C membership in `org_id`, deny.
3. If C18D has no enabled binding from `module_id` to `org_id`, deny.
4. If membership role is `admin`, allow `read`, `write`, and `execute`.
5. If membership role is `member`, allow `read`.
6. Apply module-level action policy.

## 3. Org Isolation Rules

Permissions are scoped to the target organization. No permission inheritance is
allowed across organizations.

Rule:

```text
user not active in target org_id -> DENY
```

This is implemented via C18C `org_memberships`.

## 4. Module Isolation Rules

C18F treats C18D binding as a mandatory execution precondition:

```text
module not bound to org -> DENY
module bound but role/action denied -> DENY
```

Module-level action policy:

- `K-series`: `read`, `write`, `execute`
- `C-series`: `admin`
- `P-series`: `write`

## 5. Owner Override

Global owner is derived from `users.role`, not module visibility:

```text
if user.role == "owner": RETURN ALLOW
```

Owner can access every org, every module, and every supported action.

## 6. API Middleware Design

`backend/app/middleware/permission.py` intercepts API requests and enforces
C18F when a request provides org/module execution context through path, query,
or headers.

It covers:

- API requests
- module access
- C15 workflow execution paths
- C14 AI execution paths
- C17 logs access paths

Legacy routes without org/module context are observed but not force-denied by
C18F; C17 remains responsible for data-layer filtering.

## 7. C18 Integration

- C18C: authoritative source for active org membership and membership role.
- C18D: authoritative source for module-to-org binding.
- C18E: visibility remains advisory for UI/rendering and never grants execution.

C18F does not modify C18A-E.

## 8. Security Boundary

C18F controls what action a user may execute in an org/module context.

It explicitly does not mean:

- permission equals visibility
- permission equals data access
- module visibility equals module execution permission

C17 remains the data access and audit data boundary.
