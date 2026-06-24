export const ROLE_OWNER = "owner";
export const ROLE_ADMIN = "admin";
export const ROLE_SUPER_ADMIN = "super_admin";

export function normalizeRole(role: string | null | undefined) {
  if (!role) {
    return "";
  }

  const normalized = role
    .trim()
    .toLowerCase()
    .replace(/-/g, "_")
    .replace(/\s+/g, "_");
  if (
    normalized === "superadmin" ||
    normalized === "super_admin" ||
    normalized === "org_admin" ||
    normalized === "organization_admin"
  ) {
    return ROLE_SUPER_ADMIN;
  }

  return normalized;
}

export function isOwnerRole(role: string | null | undefined) {
  return normalizeRole(role) === ROLE_OWNER;
}

export function isSuperAdminRole(role: string | null | undefined) {
  return normalizeRole(role) === ROLE_SUPER_ADMIN;
}

export function isOrgAdminLikeRole(role: string | null | undefined) {
  const normalized = normalizeRole(role);
  return normalized === ROLE_SUPER_ADMIN || normalized === ROLE_ADMIN;
}

export function canManageUsersForRole(role: string | null | undefined) {
  return isOwnerRole(role) || isOrgAdminLikeRole(role);
}
