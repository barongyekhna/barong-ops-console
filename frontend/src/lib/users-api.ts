import { ApiError, apiRequest } from "@/lib/api";

export const MANAGED_USER_ROLES = [
  "owner",
  "super_admin",
  "operator",
  "viewer",
  "reviewer",
] as const;

export type ManagedUserRole = (typeof MANAGED_USER_ROLES)[number];

export type UserRoleMetadata = {
  name: string;
  label: string;
  description: string;
  human_or_agent: string;
  c04_status: string;
  assignable: boolean;
};

export type UserRolesResponse = {
  assignable_roles: UserRoleMetadata[];
  standard_roles: UserRoleMetadata[];
};

export type ManagedUser = {
  id: number;
  username: string;
  role: string;
  job_title: string | null;
  organization_id: string | null;
  must_change_password: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
};

export type UserListResponse = {
  items: ManagedUser[];
  count: number;
  limit: number;
  offset: number;
  degraded?: boolean;
  source?: string;
};

export type OrganizationOption = {
  org_id: string;
  org_name: string;
  org_type: string;
  status: string;
  owner_user_id: string;
};

export type OrganizationListResponse = {
  items: OrganizationOption[];
  count: number;
  limit: number;
  offset: number;
  degraded?: boolean;
  source?: string;
};

export type CreateUserPayload = {
  username: string;
  job_title?: string | null;
  organization_id?: string | null;
  role: ManagedUserRole;
};

export type UpdateUserPayload = {
  role?: ManagedUserRole;
  is_active?: boolean;
};

export const USERS_PAGE_LIMIT = 10;

export function isManagedUserRole(role: string): role is ManagedUserRole {
  return MANAGED_USER_ROLES.includes(role as ManagedUserRole);
}

export function listUsers(
  limit = USERS_PAGE_LIMIT,
  offset = 0,
  options: { organizationId?: string | null } = {},
) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (options.organizationId) {
    params.set("organization_id", options.organizationId);
  }

  return apiRequest<UserListResponse>(`/users?${params.toString()}`, {
    method: "GET",
  });
}

export async function listSuperAdminUsers(limit = 100, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    role: "super_admin",
  });
  const result = await apiRequest<UserListResponse>(
    `/users?${params.toString()}`,
    {
      method: "GET",
    },
  );
  const items = result.items.filter((user) => user.role === "super_admin");

  return {
    ...result,
    count: items.length,
    items,
  };
}

export function listUserRoles() {
  return apiRequest<UserRolesResponse>("/users/roles", {
    method: "GET",
  });
}

export function listOrganizations(limit = USERS_PAGE_LIMIT, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  return apiRequest<OrganizationListResponse>(
    `/organizations?${params.toString()}`,
    {
      method: "GET",
    },
  );
}

export function createUser(payload: CreateUserPayload) {
  return apiRequest<ManagedUser>("/users", {
    body: payload,
    method: "POST",
  });
}

export function getUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}`, {
    method: "GET",
  });
}

export function updateUser(
  userId: number,
  payload: UpdateUserPayload,
) {
  return apiRequest<ManagedUser>(`/users/${userId}`, {
    body: payload,
    method: "PATCH",
  });
}

export function disableUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}/disable`, {
    method: "POST",
  });
}

export function enableUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}/enable`, {
    method: "POST",
  });
}

export function resetUserPassword(
  userId: number,
  newPassword: string,
) {
  return apiRequest<ManagedUser>(`/users/${userId}/reset-password`, {
    body: { new_password: newPassword },
    method: "POST",
  });
}

export function formatUsersApiError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) {
    return fallback;
  }

  if (error.status === 401) {
    return "请重新登录后再管理账号。";
  }
  if (error.status === 403) {
    return "仅所有者和组织管理员可以管理账号。";
  }
  if (error.status === 409) {
    return "该用户名已存在，请更换后重试。";
  }
  if (error.status === 404) {
    return "未找到对应账号，请刷新后重试。";
  }
  if (error.status === 422) {
    return "请检查用户名、角色和组织后再提交。";
  }
  if (error.status === 503) {
    return "加载失败，请稍后重试。";
  }
  if (error.status >= 500) {
    return "加载失败，请稍后重试。";
  }

  return fallback;
}
