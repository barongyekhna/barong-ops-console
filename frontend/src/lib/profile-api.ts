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

export function getMyProfile(): Promise<ProfileMe> {
  return apiRequest<ProfileMe>("/profile/me");
}

export function updateMyProfile(patch: {
  nickname?: string | null;
  theme_pref?: ThemePref;
}): Promise<ProfileMe> {
  return apiRequest<ProfileMe>("/profile/me", { method: "PATCH", body: patch });
}

/**
 * 头像上传是 multipart。
 *
 * 这个函数的原注释写着「所以它绕过 apiRequest（那个会把 body JSON 化）」——
 * 2026-09-02 起不再成立：`apiRequest` 认得 FormData，不会 stringify、也不会
 * 手动设 Content-Type（multipart 的 boundary 由 fetch 自己按 FormData 生成，
 * 手动设就没了）。绕过的代价是它自己抄了一份会话头、少了超时和 401 派发。
 */
export async function uploadMyAvatar(file: File): Promise<ProfileMe> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<ProfileMe>("/profile/me/avatar", {
    body: form,
    fallbackMessage: "头像上传失败,请重试。",
    method: "POST",
  });
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
