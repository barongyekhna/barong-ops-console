import { apiRequest } from "@/lib/api";

export type AuthenticatedUser = {
  id: number;
  username: string;
  role: string;
  must_change_password: boolean;
  is_active: boolean;
  last_login_at: string | null;
};

type AuthenticatedUserPayload = AuthenticatedUser & {
  permissions?: unknown;
};

type SessionUserPayload = AuthenticatedUserPayload;

type LoginResponsePayload = {
  message?: string | null;
  require_password_change?: boolean;
  user: AuthenticatedUserPayload;
};

type LoginResponse = {
  message: string | null;
  require_password_change: boolean;
  user: AuthenticatedUser;
};

type AuthRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

function normalizeAuthenticatedUser(
  user: AuthenticatedUserPayload,
): AuthenticatedUser {
  const { permissions: _permissions, ...identity } = user;

  return {
    ...identity,
    must_change_password: user.must_change_password === true,
  };
}

function normalizeSessionUser(user: SessionUserPayload): AuthenticatedUser {
  return normalizeAuthenticatedUser(user);
}

export async function loginRequest(
  username: string,
  password: string,
  options: AuthRequestOptions = {},
) {
  const response = await apiRequest<LoginResponsePayload>("/auth/login", {
    body: { username, password },
    method: "POST",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  });

  return {
    ...response,
    message: response.message ?? null,
    require_password_change:
      response.require_password_change === true ||
      response.user.must_change_password === true,
    user: normalizeAuthenticatedUser(response.user),
  };
}

export async function changePasswordRequest(
  currentPassword: string,
  newPassword: string,
  options: AuthRequestOptions = {},
) {
  const response = await apiRequest<LoginResponsePayload>(
    "/auth/change-password",
    {
      body: {
        current_password: currentPassword,
        new_password: newPassword,
      },
      method: "POST",
      signal: options.signal,
      timeoutMs: options.timeoutMs,
    },
  );

  return {
    message: response.message ?? null,
    require_password_change: response.user.must_change_password === true,
    user: normalizeAuthenticatedUser(response.user),
  };
}

export async function sessionCheckRequest(options: AuthRequestOptions = {}) {
  const user = await apiRequest<SessionUserPayload>("/auth/me", {
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  });

  return normalizeSessionUser(user);
}

export async function currentUserRequest(options: AuthRequestOptions = {}) {
  return sessionCheckRequest(options);
}

export function logoutRequest() {
  return apiRequest<{ message: string }>("/auth/logout", {
    method: "POST",
  });
}
