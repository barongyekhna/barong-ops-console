import { apiRequest } from "@/lib/api";

export type ThemePref = "light" | "dark" | "system";

export type ProfileMe = {
  user_id: number;
  username: string;
  display_name: string;
  nickname: string | null;
  avatar_url: string | null;
  theme_pref: ThemePref;
  bio: string | null;
};

const AUTH_STORAGE_KEY = "barong-auth-session";

function storedSessionToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { sessionToken?: unknown };
    return typeof parsed.sessionToken === "string" ? parsed.sessionToken : null;
  } catch {
    return null;
  }
}

export function getMyProfile(): Promise<ProfileMe> {
  return apiRequest<ProfileMe>("/profile/me");
}

export function updateMyProfile(patch: {
  nickname?: string | null;
  theme_pref?: ThemePref;
}): Promise<ProfileMe> {
  return apiRequest<ProfileMe>("/profile/me", { method: "PATCH", body: patch });
}

/** Avatar upload is multipart, so it bypasses apiRequest (which JSON-encodes bodies). */
export async function uploadMyAvatar(file: File): Promise<ProfileMe> {
  const form = new FormData();
  form.append("file", file);
  const headers = new Headers({ Accept: "application/json" });
  const token = storedSessionToken();
  if (token) {
    headers.set("X-Session-Token", token);
  }
  const response = await fetch("/api/backend/profile/me/avatar", {
    method: "POST",
    body: form,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let detail = "头像上传失败,请重试。";
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await response.json()) as ProfileMe;
}

// --- MCP 个人钥匙(Codex 等外部代理接入控制台的身份) ---------------------------

export type McpTokenSummary = {
  has_token: boolean;
  status: "active" | "disabled" | null;
  token_prefix: string | null;
  rotated_at: string | null;
  last_used_at: string | null;
};

export type McpAccessMe = {
  summary: McpTokenSummary;
  eligible: boolean;
  server_name: string;
  server_url: string;
  verify_hint: string;
};

/** 明文只回这一次;之后只剩哈希,再看不到。 */
export type McpTokenIssued = {
  token: string;
  summary: McpTokenSummary;
  setup_command_mac: string;
  setup_command_windows: string;
  server_name: string;
  server_url: string;
  verify_hint: string;
};

export function getMyMcpAccess(): Promise<McpAccessMe> {
  return apiRequest<McpAccessMe>("/profile/me/mcp");
}

export function resetMyMcpToken(): Promise<McpTokenIssued> {
  return apiRequest<McpTokenIssued>("/profile/me/mcp/reset", { method: "POST" });
}
