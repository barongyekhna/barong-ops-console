export type RMarket = "Amazon" | "独立站" | "Both";
export type RChannelRecommendation = "amazon" | "site" | "dual";

export type RCommerceRunRequest = {
  main_keyword: string;
  category: string;
  market: RMarket;
  price_range: string;
  risk_level: "low" | "medium" | "high";
  target_count: number;
  task_budget_usd: number;
};

export type RReason = {
  text: string;
  source: "deepseek_v4_pro";
};

export type RSupplier = {
  organization_id: string;
  supplier_name: string;
  product_link: string;
  link?: string | null;
  preview_image: string;
  price_range: string;
  MOQ: number;
  dropshipping_support: boolean;
  moq_1_allowed: boolean;
  sample_availability: boolean;
  shipping_origin: string;
  rating: number | null;
  provider: string;
  mock: boolean;
};

export type RSizeWeight = {
  length_cm: number;
  width_cm: number;
  height_cm: number;
  weight_kg: number;
  package_type: string;
  shipping_class: string;
};

export type RProductCandidate = {
  organization_id: string;
  candidate_id: string;
  main_keyword: string;
  market: RMarket;
  channel_recommendation: RChannelRecommendation;
  supplier_list: RSupplier[];
  supply_chain_incomplete: boolean;
  purchase_price_range: string;
  selling_price: string;
  size_weight: RSizeWeight;
  reason: RReason;
  decision_summary: {
    decision?: string;
    final_score?: number;
    risk_level?: string;
    recommended_next_step?: string;
  };
  provider_contract: Record<string, unknown>;
};

export type RCommerceRunResponse = {
  report_name: string;
  generated_at: string;
  engine: string;
  engine_version: string;
  organization_id: string;
  organization_name: string;
  provider_mode: "mock";
  api_key_dependency: boolean;
  future_v3_key_ready: boolean;
  required_skills: string[];
  selected_products: RProductCandidate[];
  supplier_data: Array<Record<string, unknown>>;
  budget_usage: Record<string, unknown>;
  crawl_count: number;
  crawl_records: Array<Record<string, unknown>>;
  reason_outputs: Array<Record<string, unknown>>;
  decision_outputs: Array<Record<string, unknown>>;
  save_remove_logs: Array<Record<string, unknown>>;
  rejected_candidates: Array<Record<string, unknown>>;
  storage: Record<string, unknown>;
  scope_guard: Record<string, unknown>;
};

export type RCommerceReviewResponse = {
  status: "saved" | "removed";
  log: Record<string, unknown>;
  database_path: string;
  report_path: string;
};

export type RCommerceSkillResponse = {
  engine: string;
  engine_version: string;
  organization_id: string;
  organization_name: string;
  provider_mode: "mock";
  required_skills: string[];
  skills: Record<
    string,
    {
      status?: string;
      functions?: string[];
      input?: string;
      output?: string;
      deepseek_call?: string;
      provider?: string;
      type?: string;
    }
  >;
};
