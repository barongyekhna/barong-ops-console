export type ResearchRunStatus = "pending" | "running" | "completed" | "failed";

export type ResearchRunSource = "k15_trigger" | "manual" | "system";

export type ResearchRun = {
  id: string;
  product_id: string;
  status: ResearchRunStatus;
  query_type: "keyword_research";
  created_at: string;
  updated_at: string;
  keywords: string[];
  competitor_brands: string[];
  search_intent: string;
  source: ResearchRunSource;
  confidence_score: number;
};

export type ResearchTriggerUiState =
  | "idle"
  | "pending"
  | "running"
  | "completed";
