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
    mode: "batch_processor_only" | "realtime_inline";
    model?: string;
    controls_execution: boolean;
    run_time_range: string;
    total_processed: number;
    pass_count: number;
    fail_count: number;
    deleted_count: number;
    interval_seconds?: number;
    batch_size?: number;
    max_runtime_seconds?: number;
    schedule_enabled?: boolean;
    window_start?: string | null;
    window_end?: string | null;
    timezone?: string;
    stopped_by_deadline?: boolean;
  };
  category_tree: {
    selected_count: number;
    selected_categories: string[];
    runnable_selected_count?: number;
    runnable_selected_categories?: string[];
  };
  runtime: RwRuntimeOverview;
};

export type RwProduct = {
  asin: string;
  marketplace: string;
  source_query: string | null;
  title: string;
  title_zh: string | null;
  title_zh_source: string | null;
  title_zh_updated_at: string | null;
  image_url: string | null;
  brand: string | null;
  category: string;
  price: number | null;
  bsr: number;
  reviews: number;
  seller_count: number;
  landed_cost: number | null;
  margin_source: string | null;
  margin_confidence: string | null;
  fulfillment_method: string | null;
  lithium_battery_warning: boolean;
  brand_share: number | null;
  price_trend: string | null;
  rating: number | null;
  state: string;
  rule_result: string;
  rule_reject_reason: string | null;
  margin: number | null;
  category_id: string | null;
  category_path: string[];
  skill_score: number | null;
  features: Record<string, unknown>;
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
  has_next?: boolean;
  has_previous?: boolean;
  returned_count?: number;
  items: RwProduct[];
  mode: "production";
  organization: string;
  page?: number;
  page_size?: number;
  storage_status?: string;
  total_pages?: number;
  filters?: {
    q: string | null;
    category_id: string | null;
    page?: number;
    page_size?: number;
    state: string | null;
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

export type RwRuntimeSettings = {
  deepseek_interval_seconds: number;
  deepseek_batch_size: number;
  deepseek_max_runtime_seconds: number;
  deepseek_schedule_enabled: boolean;
  deepseek_window_start: string;
  deepseek_window_end: string;
  deepseek_timezone: string;
  keepa_batch_size: number;
  discovery_categories_per_cycle: number;
  keepa_429_backoff_seconds: number;
  selected_categories: string[] | null;
};

export type RwSettingsResponse = {
  module: "R-W";
  organization: string;
  settings: RwRuntimeSettings;
  mode: "production";
};

export type RwCategoryNode = {
  id: string;
  name: string;
  children: RwCategoryNode[];
  selected: boolean;
};

export type RwCategoryTreeResponse = {
  source?: string;
  generated_from?: string;
  redline_terms?: string[];
  root: RwCategoryNode;
  selected_categories: string[];
  runnable_selected_categories?: string[];
  selected_count?: number;
  runnable_selected_count?: number;
  queue_pruned?: number;
};
