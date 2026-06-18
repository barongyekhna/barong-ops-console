import test from "node:test";
import assert from "node:assert/strict";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  HIGH_RISK_CONFIRMATION_TEXT,
  ROLE_DEFAULT_PERMISSIONS_NOTICE,
  canShowPermissionManagementEntry,
  createGrantRequestBody,
  detectHighRiskPermission,
  filterGrantablePermissionRegistry,
  formatPermissionAssignmentsApiError,
  getAssignmentEmptyStateText,
  getPermissionRegistryPath,
  getPermissionTargetMode,
  getUserPermissionAssignmentPath,
  getUserPermissionAssignmentsPath,
  normalizePermissionAssignmentListResponse,
  requiresHighRiskUpdateConfirmation,
  shouldRefreshAssignmentsAfterMutation,
  validatePermissionGrantInput,
  validatePermissionRevokeInput,
  validatePermissionUpdateInput,
} from "../../frontend/src/lib/permission-management.ts";

const ownerPermissions = {
  assignments: [],
  is_owner_full_access: true,
  permission_keys: ["*"],
  scope_summary: [],
};

const nonOwnerPermissions = {
  assignments: [
    {
      permission_key: "permissions.manage",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["permissions.manage"],
  scope_summary: [],
};

const ordinaryPermission = {
  action: "read",
  category: "business",
  created_at: null,
  description: "View jobs.",
  id: "permission-jobs-read",
  is_enabled: true,
  is_system: true,
  label: "Read jobs",
  menu_policy: "show_locked",
  module_key: "jobs",
  permission_key: "jobs.read",
  risk_level: "low",
  updated_at: null,
};

const highRiskPermission = {
  ...ordinaryPermission,
  action: "manage",
  category: "admin",
  label: "Manage permissions",
  module_key: "permissions",
  permission_key: "permissions.manage",
  risk_level: "critical",
};

const assignmentId = "123e4567-e89b-12d3-a456-426614174000";

const highRiskAssignment = {
  created_at: "2026-06-11T00:00:00Z",
  description: "Grant or revoke permissions.",
  effective: false,
  enabled: false,
  expires_at: null,
  granted_by_user_id: 1,
  high_risk: true,
  id: assignmentId,
  is_enabled: false,
  permission_key: "permissions.manage",
  permission_name: "Manage permissions",
  reason: "Temporary coverage.",
  risk_level: "critical",
  scope_id: "*",
  scope_key: "*",
  scope_type: "global",
  updated_at: "2026-06-11T00:00:00Z",
  user_id: 2,
};

test("constructs C06B permission assignment API paths", () => {
  assert.equal(
    getUserPermissionAssignmentsPath(42),
    "/permissions/users/42/assignments",
  );
  assert.equal(
    getUserPermissionAssignmentPath(42, assignmentId),
    `/permissions/users/42/assignments/${assignmentId}`,
  );
  assert.equal(
    getPermissionRegistryPath(),
    "/permissions/registry?limit=100&offset=0",
  );
});

test("backend proxy allowlist accepts only precise permission assignment paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "permissions",
      "users",
      "42",
      "assignments",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "permissions",
      "users",
      "42",
      "assignments",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("PATCH", [
      "permissions",
      "users",
      "42",
      "assignments",
      assignmentId,
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("DELETE", [
      "permissions",
      "users",
      "42",
      "assignments",
      assignmentId,
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "permissions",
      "users",
      "42",
      "assignments",
      assignmentId,
    ]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("DELETE", [
      "permissions",
      "users",
      "42",
      "assignments",
      "not-a-uuid",
    ]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["permissions", "wildcard"]),
    false,
  );
});

test("detects high-risk permissions using C06B-compatible rules", () => {
  assert.equal(detectHighRiskPermission(ordinaryPermission), false);
  assert.equal(detectHighRiskPermission(highRiskPermission), true);
  assert.equal(
    detectHighRiskPermission({
      permission_key: "users.manage",
      risk_level: "medium",
    }),
    true,
  );
  assert.equal(
    detectHighRiskPermission({
      module_key: "production",
      permission_key: "release.approve",
      risk_level: "low",
    }),
    true,
  );
  assert.equal(
    detectHighRiskPermission({
      action: "manage",
      category: "system",
      permission_key: "system.admin",
      risk_level: "medium",
    }),
    true,
  );
});

test("filters wildcard and disabled permissions from grant options", () => {
  const grantable = filterGrantablePermissionRegistry([
    ordinaryPermission,
    { ...ordinaryPermission, permission_key: "*", id: "wildcard" },
    {
      ...ordinaryPermission,
      id: "disabled",
      is_enabled: false,
      permission_key: "jobs.manage",
    },
  ]);

  assert.deepEqual(
    grantable.map((permission) => permission.permission_key),
    ["jobs.read"],
  );
});

test("permission management copy stays explicit about explicit assignments", () => {
  assert.match(ROLE_DEFAULT_PERMISSIONS_NOTICE, /explicit permission assignments/);
  assert.doesNotMatch(ROLE_DEFAULT_PERMISSIONS_NOTICE, /RBAC|role default/i);
});

test("permission management entry is visible only for owner full access", () => {
  assert.equal(canShowPermissionManagementEntry(ownerPermissions), true);
  assert.equal(canShowPermissionManagementEntry(nonOwnerPermissions), false);
});

test("owner target uses full access mode and empty non-owner assignment list shows empty state", () => {
  assert.equal(
    getPermissionTargetMode({ role: "owner" }, null),
    "owner_full_access",
  );
  assert.equal(
    getPermissionTargetMode(
      { role: "viewer" },
      {
        assignments: [],
        is_owner_full_access: true,
        owner_full_access_note: "Owner full access.",
        role: "owner",
        user_id: 1,
        username: "owner",
      },
    ),
    "owner_full_access",
  );
  assert.equal(
    getAssignmentEmptyStateText({
      assignments: [],
      is_owner_full_access: false,
      owner_full_access_note: null,
      role: "viewer",
      user_id: 2,
      username: "viewer",
    }),
    "No explicit assignments yet.",
  );
});

test("normal grant validation builds the expected frontend payload and API body", () => {
  const result = validatePermissionGrantInput({
    confirm_high_risk: false,
    confirmation_text: "",
    enabled: true,
    expires_at: "2026-07-11T00:00",
    permission: ordinaryPermission,
    permission_key: " jobs.read ",
    reason: "",
    scope_id: "jobs",
    scope_type: "module",
  });

  assert.equal(result.ok, true);
  assert.deepEqual(result.payload, {
    confirm_high_risk: false,
    confirmation_text: null,
    enabled: true,
    expires_at: "2026-07-11T00:00",
    permission_key: "jobs.read",
    reason: null,
    scope_id: "jobs",
    scope_type: "module",
  });
  assert.deepEqual(createGrantRequestBody(result.payload), {
    confirm_high_risk: false,
    confirmation_text: null,
    expires_at: "2026-07-11T00:00",
    permission_key: "jobs.read",
    reason: null,
    scope_id: "jobs",
    scope_type: "module",
  });
});

test("high-risk grant is blocked without reason or confirmation", () => {
  const missingReason = validatePermissionGrantInput({
    confirm_high_risk: true,
    confirmation_text: HIGH_RISK_CONFIRMATION_TEXT,
    enabled: true,
    expires_at: "",
    permission: highRiskPermission,
    permission_key: "permissions.manage",
    reason: "",
    scope_id: "*",
    scope_type: "global",
  });
  const missingConfirmation = validatePermissionGrantInput({
    confirm_high_risk: false,
    confirmation_text: "",
    enabled: true,
    expires_at: "",
    permission: highRiskPermission,
    permission_key: "permissions.manage",
    reason: "Temporary admin coverage.",
    scope_id: "*",
    scope_type: "global",
  });

  assert.equal(missingReason.ok, false);
  assert.equal(missingConfirmation.ok, false);
});

test("high-risk grant with confirmation includes confirm fields", () => {
  const result = validatePermissionGrantInput({
    confirm_high_risk: true,
    confirmation_text: HIGH_RISK_CONFIRMATION_TEXT,
    enabled: true,
    expires_at: "",
    permission: highRiskPermission,
    permission_key: "permissions.manage",
    reason: "Temporary admin coverage.",
    scope_id: "*",
    scope_type: "global",
  });

  assert.equal(result.ok, true);
  assert.equal(result.payload.confirm_high_risk, true);
  assert.equal(result.payload.confirmation_text, HIGH_RISK_CONFIRMATION_TEXT);
});

test("high-risk update requires confirmation when re-enabled or scope changes", () => {
  assert.equal(
    requiresHighRiskUpdateConfirmation(highRiskAssignment, {
      confirm_high_risk: false,
      confirmation_text: "",
      enabled: true,
      expires_at: "",
      reason: "Resume.",
      scope_id: "*",
      scope_type: "global",
    }),
    true,
  );

  const blocked = validatePermissionUpdateInput(highRiskAssignment, {
    confirm_high_risk: false,
    confirmation_text: "",
    enabled: true,
    expires_at: "",
    reason: "Resume.",
    scope_id: "*",
    scope_type: "global",
  });
  const allowed = validatePermissionUpdateInput(highRiskAssignment, {
    confirm_high_risk: true,
    confirmation_text: HIGH_RISK_CONFIRMATION_TEXT,
    enabled: true,
    expires_at: "",
    reason: "Resume.",
    scope_id: "*",
    scope_type: "global",
  });

  assert.equal(blocked.ok, false);
  assert.equal(allowed.ok, true);
  assert.equal(allowed.payload.confirm_high_risk, true);
});

test("high-risk revoke is blocked without reason", () => {
  const blocked = validatePermissionRevokeInput(highRiskAssignment, "");
  const allowed = validatePermissionRevokeInput(
    highRiskAssignment,
    "No longer needed.",
  );

  assert.equal(blocked.ok, false);
  assert.equal(allowed.ok, true);
  assert.deepEqual(allowed.payload, { reason: "No longer needed." });
});

test("revoke success path marks assignments for refresh", () => {
  assert.equal(shouldRefreshAssignmentsAfterMutation("revoke"), true);
});

test("assignment response normalization safely downgrades missing fields", () => {
  assert.deepEqual(
    normalizePermissionAssignmentListResponse(
      {
        assignments: [{ enabled: true, permission_key: "jobs.read" }],
      },
      7,
    ),
    {
      assignments: [
        {
          created_at: null,
          description: null,
          effective: false,
          enabled: true,
          expires_at: null,
          granted_by_user_id: null,
          high_risk: false,
          id: "",
          is_enabled: true,
          permission_key: "jobs.read",
          permission_name: null,
          reason: null,
          risk_level: null,
          scope_id: "",
          scope_key: "",
          scope_type: "global",
          updated_at: null,
          user_id: 7,
        },
      ],
      is_owner_full_access: false,
      owner_full_access_note: null,
      role: "",
      user_id: 7,
      username: "",
    },
  );
});

test("403, 409, and 422 errors produce safe summaries without sensitive values", () => {
  assert.equal(
    formatPermissionAssignmentsApiError({
      message: "Authorization: Bearer abc.def.ghi",
      status: 403,
    }),
    "Only an owner can manage permissions.",
  );
  assert.equal(
    formatPermissionAssignmentsApiError({
      message: "duplicate active assignment",
      status: 409,
    }),
    "This assignment already exists or conflicts with current access.",
  );
  assert.equal(
    formatPermissionAssignmentsApiError({
      message: "invalid payload",
      status: 422,
    }),
    "The request is incomplete or invalid. Check permission, scope, expires_at, and reason.",
  );
  assert.doesNotMatch(
    formatPermissionAssignmentsApiError({
      message: "Authorization: Bearer abc.def.ghi",
      status: 400,
    }),
    /abc\.def\.ghi/,
  );
});
