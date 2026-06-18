import { apiRequest } from "@/lib/api";
import {
  normalizeCurrentUserPermissions,
  type FrontendPermissions,
} from "@/lib/permissions";

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

type SessionUserPayload = Omit<AuthenticatedUser, "permissions">;

type LoginResponsePayload = {
  user: AuthenticatedUserPayload;
};

type LoginResponse = {
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

function normalizeSessionUser(user: SessionUserPayload): AuthenticatedUser {
  return {
    ...user,
    permissions: null,
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

export async function sessionCheckRequest() {
  const user = await apiRequest<SessionUserPayload>("/auth/me", {
    method: "GET",
  });

  return normalizeSessionUser(user);
}

export async function currentUserRequest() {
  return sessionCheckRequest();
}

export function logoutRequest() {
  return apiRequest<{ message: string }>("/auth/logout", {
    method: "POST",
  });
}
