import { ApiError, apiRequest } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export const MANAGED_USER_ROLES = [
  "viewer",
  "operator",
  "reviewer",
] as const;

export type ManagedUserRole = (typeof MANAGED_USER_ROLES)[number];

export type ManagedUser = {
  id: number;
  username: string;
  role: string;
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
};

export type CreateUserPayload = {
  username: string;
  password: string;
  role: ManagedUserRole;
};

export type UpdateUserPayload = {
  role?: ManagedUserRole;
  is_active?: boolean;
};

export function isManagedUserRole(role: string): role is ManagedUserRole {
  return MANAGED_USER_ROLES.includes(role as ManagedUserRole);
}

export function listUsers(limit = 50, offset = 0) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  return apiRequest<UserListResponse>(`/users?${params.toString()}`, {
    accessToken: readAccessToken(),
    method: "GET",
  });
}

export function createUser(payload: CreateUserPayload) {
  return apiRequest<ManagedUser>("/users", {
    accessToken: readAccessToken(),
    body: payload,
    method: "POST",
  });
}

export function getUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}`, {
    accessToken: readAccessToken(),
    method: "GET",
  });
}

export function updateUser(
  userId: number,
  payload: UpdateUserPayload,
) {
  return apiRequest<ManagedUser>(`/users/${userId}`, {
    accessToken: readAccessToken(),
    body: payload,
    method: "PATCH",
  });
}

export function disableUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}/disable`, {
    accessToken: readAccessToken(),
    method: "POST",
  });
}

export function enableUser(userId: number) {
  return apiRequest<ManagedUser>(`/users/${userId}/enable`, {
    accessToken: readAccessToken(),
    method: "POST",
  });
}

export function resetUserPassword(
  userId: number,
  newPassword: string,
) {
  return apiRequest<ManagedUser>(`/users/${userId}/reset-password`, {
    accessToken: readAccessToken(),
    body: { new_password: newPassword },
    method: "POST",
  });
}

export function formatUsersApiError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) {
    return fallback;
  }

  if (error.status === 401) {
    return "Sign in again before managing console accounts.";
  }
  if (error.status === 403) {
    return "Only owner accounts can manage console users.";
  }
  if (error.status === 409) {
    return "That username already exists. Choose a different username.";
  }
  if (error.status === 404) {
    return "The selected user was not found. Refresh the list and try again.";
  }
  if (error.status === 422) {
    return error.message === "The request could not be completed."
      ? "Check the username, role, and password. Passwords must be 12 to 256 characters."
      : error.message;
  }
  if (error.status === 503) {
    return "The backend API service is unavailable.";
  }

  return error.message || fallback;
}
