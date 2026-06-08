import { apiRequest } from "@/lib/api";

export const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";

export type AuthenticatedUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthenticatedUser;
};

export function loginRequest(username: string, password: string) {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export function currentUserRequest(accessToken: string) {
  return apiRequest<AuthenticatedUser>("/auth/me", {
    accessToken,
    method: "GET",
  });
}

export function logoutRequest(accessToken: string) {
  return apiRequest<{ message: string }>("/auth/logout", {
    accessToken,
    method: "POST",
  });
}
