export type KeywordSource = "K15" | "K16" | "K17" | "K18" | "manual";

export type KeywordStatus = "active" | "archived" | "suggested" | "edited";

export type KeywordEntry = {
  id: string;
  product_id: string;
  keyword: string;
  source: KeywordSource;
  status: KeywordStatus;
  created_at: string;
  updated_at: string;
};

export type CreateKeywordPayload = {
  keyword: string;
  product_id: string;
  source: KeywordSource;
  status?: KeywordStatus | null;
};

export type UpdateKeywordPayload = {
  keyword?: string;
  product_id?: string;
  source?: KeywordSource;
  status?: KeywordStatus;
};

export type KeywordEntryResponse = {
  keyword_entry: KeywordEntry;
  status: "created" | "updated" | "archived";
  timestamp: string;
};

export type KeywordListResponse = {
  keyword_entries: KeywordEntry[];
  status: "ok";
  timestamp: string;
};

export const keywordSources: KeywordSource[] = [
  "K15",
  "K16",
  "K17",
  "K18",
  "manual",
];

export const keywordStatuses: KeywordStatus[] = [
  "active",
  "archived",
  "suggested",
  "edited",
];

export const sourceLabels: Record<KeywordSource, string> = {
  K15: "调研",
  K16: "SERP",
  K17: "ChatGPT",
  K18: "Claude",
  manual: "人工录入",
};

export const keywordStatusLabels: Record<KeywordStatus, string> = {
  active: "启用",
  archived: "已归档",
  edited: "已编辑",
  suggested: "建议",
};
