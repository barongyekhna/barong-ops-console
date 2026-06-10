import test from "node:test";
import assert from "node:assert/strict";

import {
  canAccessModule,
  getPermissionAccessState,
  getRoutePermissionDecision,
  hasPermission,
  isOwnerFullAccess,
  normalizeCurrentUserPermissions,
} from "../../frontend/src/lib/permissions.ts";

const ownerPermissions = {
  assignments: [],
  is_owner_full_access: true,
  permission_keys: ["*"],
  scope_summary: [],
};

const noPermissions = {
  assignments: [],
  is_owner_full_access: false,
  permission_keys: [],
  scope_summary: [],
};

const jobsReadPermissions = {
  assignments: [
    {
      permission_key: "jobs.read",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["jobs.read"],
  scope_summary: [
    {
      permission_keys: ["jobs.read"],
      scope_key: "*",
      scope_type: "global",
    },
  ],
};

const usersManagePermissions = {
  assignments: [
    {
      permission_key: "users.manage",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["users.manage"],
  scope_summary: [],
};

const jobsModule = {
  category: "business",
  denied_behavior: "show_locked",
  href: "/jobs",
  required_permission: "jobs.read",
};

const usersModule = {
  category: "admin",
  denied_behavior: "hide_when_denied",
  href: "/users",
  owner_only: true,
  required_permission: "users.manage",
};

test("owner full access can see and access business and admin modules", () => {
  assert.equal(isOwnerFullAccess(ownerPermissions), true);
  assert.equal(hasPermission(ownerPermissions, "jobs.read"), true);
  assert.equal(canAccessModule(ownerPermissions, jobsModule), true);
  assert.deepEqual(getPermissionAccessState(ownerPermissions, jobsModule), {
    canAccess: true,
    isLocked: false,
    isVisible: true,
  });
  assert.deepEqual(getPermissionAccessState(ownerPermissions, usersModule), {
    canAccess: true,
    isLocked: false,
    isVisible: true,
  });
});

test("business modules remain visible but locked for a user without permission", () => {
  assert.equal(canAccessModule(noPermissions, jobsModule), false);
  assert.deepEqual(getPermissionAccessState(noPermissions, jobsModule), {
    canAccess: false,
    isLocked: true,
    isVisible: true,
  });
});

test("a user with a business permission does not see that module as locked", () => {
  assert.equal(hasPermission(jobsReadPermissions, "jobs.read"), true);
  assert.deepEqual(
    getPermissionAccessState(jobsReadPermissions, jobsModule),
    {
      canAccess: true,
      isLocked: false,
      isVisible: true,
    },
  );
});

test("direct access to a protected route without permission is denied", () => {
  assert.deepEqual(
    getRoutePermissionDecision(noPermissions, "/jobs", [jobsModule]),
    {
      canAccess: false,
      isLocked: true,
      isProtected: true,
      isVisible: true,
    },
  );
});

test("auth/me permissions missing or malformed safely downgrade to no access", () => {
  assert.equal(normalizeCurrentUserPermissions(undefined), null);
  assert.equal(normalizeCurrentUserPermissions(null), null);
  assert.equal(hasPermission(null, "jobs.read"), false);
  assert.deepEqual(
    normalizeCurrentUserPermissions({
      assignments: "invalid",
      is_owner_full_access: false,
      permission_keys: "invalid",
      scope_summary: "invalid",
    }),
    {
      assignments: [],
      is_owner_full_access: false,
      permission_keys: [],
      scope_summary: [],
    },
  );
});

test("user management remains visible and accessible only for owner full access", () => {
  assert.deepEqual(getPermissionAccessState(noPermissions, usersModule), {
    canAccess: false,
    isLocked: false,
    isVisible: false,
  });
  assert.deepEqual(
    getPermissionAccessState(usersManagePermissions, usersModule),
    {
      canAccess: false,
      isLocked: false,
      isVisible: false,
    },
  );
  assert.deepEqual(getPermissionAccessState(ownerPermissions, usersModule), {
    canAccess: true,
    isLocked: false,
    isVisible: true,
  });
});
