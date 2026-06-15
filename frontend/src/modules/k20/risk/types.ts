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
  K13: "K13 AI detected",
  K17: "K17 pre-filter",
  K18: "K18 validated",
  manual: "manual override",
};

export const riskLevelLabels: Record<RiskLevel, string> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
