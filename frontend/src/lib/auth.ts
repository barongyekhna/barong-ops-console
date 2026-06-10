import { apiRequest } from "@/lib/api";
import {
  normalizeCurrentUserPermissions,
  type FrontendPermissions,
} from "@/lib/permissions";

export const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";

export function readAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }

  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export type AuthenticatedUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  permissions: FrontendPermissions | null;
};

type AuthenticatedUserPayload = Omit<AuthenticatedUser, "permissions"> & {
  permissions?: unknown;
};

type LoginResponsePayload = {
  access_token: string;
  token_type: string;
  user: AuthenticatedUserPayload;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthenticatedUser;
};

function normalizeAuthenticatedUser(
  user: AuthenticatedUserPayload,
): AuthenticatedUser {
  return {
    ...user,
    permissions: normalizeCurrentUserPermissions(user.permissions),
  };
}

export async function loginRequest(username: string, password: string) {
  const response = await apiRequest<LoginResponsePayload>("/auth/login", {
    method: "POST",
    body: { username, password },
  });

  return {
    ...response,
    user: normalizeAuthenticatedUser(response.user),
  };
}

export async function currentUserRequest(accessToken: string) {
  const user = await apiRequest<AuthenticatedUserPayload>("/auth/me", {
    accessToken,
    method: "GET",
  });

  return normalizeAuthenticatedUser(user);
}

export function logoutRequest(accessToken: string) {
  return apiRequest<{ message: string }>("/auth/logout", {
    accessToken,
    method: "POST",
  });
}
