export type RwStatus = {
  active: boolean;
  endpoints: string[];
  mode: "production" | "production_blocked";
  mock_mode_active: boolean;
  module: "R-W";
  organization: string;
  keepa_key_bound: boolean;
  ingestion_service_ready: boolean;
  keepa_rate_limit: {
    max_requests_per_min: number;
    no_burst_mode: boolean;
    queue_based_ingestion: boolean;
    refill_aware_scheduler: boolean;
  };
  keepa_mode: {
    continuous_ingestion: boolean;
    worker_loop: string;
    only_rate_limit: string;
  };
  real_keepa_api_used: boolean;
  use_real_keepa_api: boolean;
  waiting_for_keys: boolean;
  skill: {
    installed: boolean;
    name: string;
    version: string;
    label: string;
    path: string;
  };
  deepseek_batch: {
    mode: "batch_processor_only";
    controls_execution: boolean;
    run_time_range: string;
    total_processed: number;
    pass_count: number;
    fail_count: number;
    deleted_count: number;
  };
  category_tree: {
    selected_count: number;
    selected_categories: string[];
  };
};

export type RwProduct = {
  asin: string;
  title: string;
  category: string;
  price: number | null;
  bsr: number;
  reviews: number;
  seller_count: number;
  state: string;
  rule_result: string;
  margin: number | null;
  category_id: string | null;
  category_path: string[];
  skill_score: number | null;
  source: string;
};

export type RwRule = {
  id: string;
  label: string;
  enabled: boolean;
  result: string;
  threshold: string;
};

export type RwProductsResponse = {
  count: number;
  items: RwProduct[];
  mode: "production";
  organization: string;
  storage_status?: string;
  filters?: {
    q: string | null;
    category_id: string | null;
    sort_by: string;
    sort_order: string;
  };
};

export type RwRulesResponse = {
  count: number;
  enabled: boolean;
  items: RwRule[];
  mode: "production";
};
