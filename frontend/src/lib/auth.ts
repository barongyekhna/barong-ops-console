import { apiRequest } from "@/lib/api";

export type AuthenticatedUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
};

type AuthenticatedUserPayload = AuthenticatedUser & {
  permissions?: unknown;
};

type SessionUserPayload = AuthenticatedUserPayload;

type LoginResponsePayload = {
  user: AuthenticatedUserPayload;
};

type LoginResponse = {
  user: AuthenticatedUser;
};

function normalizeAuthenticatedUser(
  user: AuthenticatedUserPayload,
): AuthenticatedUser {
  const { permissions: _permissions, ...identity } = user;

  return {
    ...identity,
  };
}

function normalizeSessionUser(user: SessionUserPayload): AuthenticatedUser {
  return normalizeAuthenticatedUser(user);
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
