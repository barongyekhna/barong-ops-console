# C18E Module Visibility System

C18E builds the org-specific module visibility layer for UI rendering only. It
does not grant data access and does not replace C18C org isolation or C17 audit
controls.

## Module Visibility Algorithm

```text
visible_modules = modules WHERE
  module.enabled == true
  AND (
    module.mode == "global"
    OR user.org_id IN module.bound_orgs
  )
```

Mode rules:

- `global`: visible to every active org context.
- `single`: visible only to the one org in `bound_orgs[0]`.
- `multi`: visible to every org listed in `bound_orgs`.

## `get_visible_modules()` Logic

Implemented in `backend/app/services/module_visibility_service.py`.

Flow:

1. Read the user's active org memberships from C18C `org_memberships`.
2. Resolve the active org context. Single-org users can resolve implicitly;
   multi-org users must pass the current `active_org_id`.
3. Read module bindings from C18D via `list_module_bindings()`.
4. Filter enabled bindings by `global` or active-org membership in `bound_orgs`.
5. Return the UI response:

```json
{
  "user_id": "101",
  "org_id": "org_1",
  "visible_modules": [
    {
      "module_id": "K-series",
      "module_name": "K-series",
      "mode": "single"
    }
  ]
}
```

## Integration

- C18C: authoritative source for active org memberships and active org context
  validation.
- C18D: authoritative source for module binding mode, `bound_orgs`, and
  `enabled`.
- C17: optional audit hook emits `module_visibility.read` through the existing
  event collector without changing C17 schemas or data access policy.

## API Design

```text
GET /org/{org_id}/visible-modules
```

The path `org_id` is the active org context after an org switch. The caller must
be authenticated and must have an active C18C membership in that org.

## Data Flow

```text
user -> C18C active org membership -> active org_id
     -> C18D module bindings
     -> C18E visibility filter
     -> visible_modules for frontend rendering
```

Org switching changes only the active org context. The frontend must refetch
`visible_modules` after a switch.

## Frontend Rules

- Render only modules returned by C18E `visible_modules`.
- Do not call the module registry directly for navigation visibility.
- Do not bypass the active org filter.
- Treat missing or failed C18E visibility state as hidden for org-scoped module
  navigation.

## Security Boundary

`visible_modules` is not data access permission. C18E only answers whether a
module should be shown in the UI for the current org context.

Data access must still be enforced by C18C org filters and C17 audit/security
controls. C18E does not implement C18F permissions, does not perform DB
migrations, and does not change module binding logic.
