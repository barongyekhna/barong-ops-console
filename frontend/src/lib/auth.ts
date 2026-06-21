import { ApiError, apiRequest } from "@/lib/api";

export type AuthenticatedUser = {
  id: number;
  username: string;
  role: string;
  organization_id: string | null;
  must_change_password: boolean;
  is_active: boolean;
  last_login_at: string | null;
};

type AuthenticatedUserPayload = AuthenticatedUser & {
  permissions?: unknown;
};

type SessionUserPayload = AuthenticatedUserPayload;

type LoginResponsePayload = {
  auth_complete?: boolean;
  message?: string | null;
  require_password_change?: boolean;
  session_token?: string;
  user: AuthenticatedUserPayload;
};

type LoginResponse = {
  auth_complete: true;
  message: string | null;
  require_password_change: boolean;
  session_token: string;
  user: AuthenticatedUser;
};

type AuthRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

export function roleBypassesPasswordReset(role: string | null | undefined) {
  const normalizedRole = role?.trim().toLowerCase().replace(/\s+/g, "_");
  return normalizedRole === "owner";
}

export function requiresPasswordChange(
  user: Pick<AuthenticatedUser, "role" | "must_change_password"> | null | undefined,
  fallback = false,
) {
  if (!user || roleBypassesPasswordReset(user.role)) {
    return false;
  }
  return fallback || user.must_change_password === true;
}

function normalizeAuthenticatedUser(
  user: AuthenticatedUserPayload,
): AuthenticatedUser {
  const { permissions: _permissions, ...identity } = user;

  return {
    ...identity,
    organization_id: identity.organization_id ?? null,
    last_login_at: identity.last_login_at ?? null,
    must_change_password: requiresPasswordChange(user),
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
    retryLimit: 0,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  });

  if (response.auth_complete !== true || !response.session_token) {
    throw new ApiError("Login session was not established.", 503);
  }

  const normalizedUser = normalizeAuthenticatedUser(response.user);

  return {
    ...response,
    auth_complete: true,
    message: response.message ?? null,
    require_password_change: requiresPasswordChange(
      normalizedUser,
      response.require_password_change === true,
    ),
    session_token: response.session_token,
    user: normalizedUser,
  } satisfies LoginResponse;
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

  const normalizedUser = normalizeAuthenticatedUser(response.user);

  return {
    message: response.message ?? null,
    require_password_change: requiresPasswordChange(normalizedUser),
    user: normalizedUser,
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
