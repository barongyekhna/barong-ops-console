export type RiskLevel = "low" | "medium" | "high" | "critical";

export type RiskCategory =
  | "legal"
  | "compliance"
  | "marketing"
  | "safety"
  | "platform";

export type RiskSource = "K13" | "K17" | "K18" | "manual";

export type RiskStatus = "active" | "resolved" | "ignored";

export type RiskTerm = {
  id: string;
  product_id: string;
  term: string;
  risk_level: RiskLevel;
  category: RiskCategory;
  source: RiskSource;
  status: RiskStatus;
  created_at: string;
  updated_at: string;
};

export type CreateRiskPayload = {
  product_id: string;
  term: string;
  risk_level: RiskLevel;
  category: RiskCategory;
  source: RiskSource;
  status?: RiskStatus | null;
};

export type UpdateRiskPayload = {
  product_id?: string;
  term?: string;
  risk_level?: RiskLevel;
  category?: RiskCategory;
  source?: RiskSource;
  status?: RiskStatus;
};

export type RiskTermResponse = {
  risk_term: RiskTerm;
  status: "created" | "updated" | "ignored";
  timestamp: string;
};

export type RiskListResponse = {
  risk_terms: RiskTerm[];
  status: "ok";
  timestamp: string;
};

export const riskLevels: RiskLevel[] = [
  "low",
  "medium",
  "high",
  "critical",
];

export const riskCategories: RiskCategory[] = [
  "legal",
  "compliance",
  "marketing",
  "safety",
  "platform",
];

export const riskSources: RiskSource[] = ["K13", "K17", "K18", "manual"];

export const riskStatuses: RiskStatus[] = ["active", "resolved", "ignored"];

export const sourceLabels: Record<RiskSource, string> = {
  K13: "AI识别",
  K17: "预过滤",
  K18: "已验证",
  manual: "人工处理",
};

export const riskLevelLabels: Record<RiskLevel, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export const riskCategoryLabels: Record<RiskCategory, string> = {
  compliance: "合规",
  legal: "法律",
  marketing: "营销",
  platform: "平台政策",
  safety: "安全",
};

export const riskStatusLabels: Record<RiskStatus, string> = {
  active: "启用",
  ignored: "已忽略",
  resolved: "已处理",
};
