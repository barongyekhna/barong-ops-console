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
  runtime: RwRuntimeOverview;
};

export type RwProduct = {
  asin: string;
  title: string;
  image_url: string | null;
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
  pipeline_decision: "pass" | "reject" | "pending_review" | string;
  last_keepa_pull: string | null;
  updated_at: string | null;
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

export type RwWorkerStatus = {
  worker_name: string;
  status: string;
  loop_interval_seconds: number;
  deepseek_interval_seconds: number;
  last_heartbeat_at: string | null;
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
  last_error: string | null;
  processed_total: number;
  failed_total: number;
  queue_pending: number;
  selected_categories: string[] | unknown;
  payload: Record<string, unknown>;
  updated_at: string | null;
};

export type RwPipelineEvent = {
  asin: string | null;
  category_id: string | null;
  event_type: string;
  stage: string;
  status: string;
  score_action: string | null;
  message: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type RwRuntimeOverview = {
  workers: RwWorkerStatus[];
  events: RwPipelineEvent[];
  counts: {
    total_products?: number;
    passed?: number;
    rejected?: number;
    pending_review?: number;
    last_product_update?: string | null;
  };
  queue: {
    total?: number;
    picked?: number;
    pending?: number;
  };
};

export type RwPipelineResponse = {
  module: "R-W";
  organization: string;
  refresh_seconds: number;
  runtime: RwRuntimeOverview;
  mode: "production";
};
