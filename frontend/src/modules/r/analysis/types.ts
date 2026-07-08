export type RaProviderRoleStatus = {
  role: string;
  service: string;
  label: string;
  configured: boolean;
  source: string;
  model_env: string | null;
  model_name: string | null;
  base_url_env: string | null;
  base_url_configured: boolean;
};

export type RaSkillFile = {
  key: string;
  label: string;
  filename: string;
  exists: boolean;
  sha256: string | null;
  bytes: number;
};

export type RaStage = {
  id: string;
  label: string;
  owner: string;
  status: string;
  description: string;
};

export type RaChannel = {
  id: string;
  label: string;
  description: string;
  manual_trigger: boolean;
};

export type RaTableStatus = {
  name: string;
  label: string;
  exists: boolean;
  row_count: number | null;
};

export type RaFrameworkStatus = {
  module: string;
  label: string;
  organization_id: string;
  status: string;
  runtime_mode: string;
  execution_enabled: boolean;
  external_calls_enabled: boolean;
  manual_trigger_only: boolean;
  data_boundary: {
    reads: string[];
    writes: string[];
    cross_module_writes: boolean;
  };
  candidate_source: {
    status: string;
    total_products: number;
    ra_eligible: number;
    deepseek_passed: number;
    rule_passed: number;
    rejected: number;
    source_table: string;
  };
  tables: RaTableStatus[];
  skill: {
    loaded: boolean;
    name: string;
    version: string;
    description: string;
    docs_dir: string;
    files: RaSkillFile[];
    channels: Array<{
      channel: string;
      files: string[];
      loaded: boolean;
    }>;
    prompt_content_exposed: boolean;
  };
  providers: {
    roles: RaProviderRoleStatus[];
    routing: Record<string, string>;
    external_calls_enabled: boolean;
  };
  profit_formula: RaProfitFormula;
  channels: RaChannel[];
  stages: RaStage[];
  next_steps: string[];
};

export type RaProfitFormula = {
  marketplace: string;
  formula_version: string;
  referral_fee_rate: number;
  seller_receipt_rate: number;
  first_mile_cny_per_kg: number;
  default_exchange_rate_usd_cny: number;
  exchange_rate_source?: string;
  exchange_rate_live?: boolean;
  exchange_rate_fetched_at?: string | null;
  exchange_rate_warning?: string | null;
  default_min_gross_margin: number;
  volume_weight_formula: string;
  chargeable_weight_rule: string;
  gross_profit_formula: string;
};

export type RaProfitSnapshot = {
  snapshot_id: string;
  candidate_id: string | null;
  asin: string;
  title: string | null;
  title_zh: string | null;
  image_url: string | null;
  image_candidates?: string[];
  category: string | null;
  amazon_price_usd?: number | null;
  sell_price_usd: number | null;
  landed_cost_usd: number | null;
  amazon_fees_usd: number | null;
  gross_profit_usd: number | null;
  gross_profit_cny: number | null;
  gross_margin: number | null;
  roi: number | null;
  confidence: string | null;
  verdict: string | null;
  warnings: string[];
  blocked_reasons: string[];
  supplier: {
    offer_id?: string | null;
    supplier_name?: string | null;
    supplier_url?: string | null;
    supplier_platform?: string | null;
    supplier_platform_label?: string | null;
    supplier_url_type?: string | null;
    supplier_detail_url?: string | null;
    supplier_search_url?: string | null;
    unit_price_cny?: number | null;
    domestic_shipping_cny?: number | null;
    moq?: number | null;
    one_piece_hint?: boolean | null;
    shipping_notice?: string | null;
  };
  formula: RaProfitFormula;
  created_at: string | null;
};

export type RaProfitSnapshotList = {
  items: RaProfitSnapshot[];
  count: number;
  formula: RaProfitFormula;
};

export type RaProfitRunResult = {
  counts: {
    processed: number;
    pass: number;
    reject: number;
    blocked: number;
  };
  items: RaProfitSnapshot[];
  formula: RaProfitFormula;
};

export type RaSupplierSearchResult = {
  asin: string;
  candidate_id: string;
  queries: string[];
  searches: Array<{
    search_id: string;
    query: string;
    platform?: string | null;
    platform_label?: string | null;
    search_url?: string | null;
    status: string;
    result_count: number;
  }>;
  offers: Array<{
    offer_id: string;
    search_id: string;
    supplier_name: string | null;
    supplier_url: string | null;
    supplier_platform?: string | null;
    supplier_platform_label?: string | null;
    supplier_url_type?: string | null;
    supplier_detail_url?: string | null;
    supplier_search_url?: string | null;
    unit_price_cny: number | null;
    domestic_shipping_cny: number | null;
    moq: number | null;
    match_score: number | null;
    one_piece_hint?: boolean | null;
    offer_status: string;
    crawler_status: string;
    warning: string | null;
    supplier_alignment?: RaSupplierAlignment | null;
  }>;
  profit_run: RaProfitRunResult | null;
  counts: {
    searches: number;
    candidate_offers: number;
    priced_offers: number;
  };
  warnings: string[];
};

export type RaManualProfitPayload = {
  asin: string;
  unit_price_cny: number;
  domestic_shipping_cny?: number | null;
  supplier_name?: string | null;
  supplier_url?: string | null;
  moq?: number | null;
  exchange_rate_usd_cny?: number | null;
  min_gross_margin?: number | null;
};

export type RaSupplierSearchPayload = {
  asin: string;
  result_limit: number;
  auto_calculate: boolean;
  exchange_rate_usd_cny?: number | null;
  min_gross_margin?: number | null;
};

export type RaAutoProfitPayload = {
  query: string;
  asin_limit?: number;
  supplier_limit?: number;
  min_gross_margin?: number | null;
  run_ai_mock?: boolean;
  selection_channel?: string;
};

export type RaAutoProfitJobPayload = RaAutoProfitPayload;

export type RaAiLayerResult = {
  layer: string;
  model_role: string;
  model_name: string;
  score: number | null;
  verdict: string | null;
  reason: string | null;
  advantages: string[];
  risks: string[];
  created_at: string | null;
};

export type RaAiSelectionResult = {
  candidate_id: string;
  asin: string | null;
  final_score: number | null;
  verdict: string | null;
  channel: string | null;
  barrier_type: string | null;
  decision_reason: string | null;
  layers: RaAiLayerResult[];
  report_id?: string | null;
  mock_pipeline_version?: string | null;
  created_at?: string | null;
};

export type RaAutoProfitItem = {
  status: string;
  candidate_id?: string | null;
  asin: string | null;
  image_url: string | null;
  image_candidates?: string[];
  keyword: string;
  product_keyword?: string | null;
  matched_source_query: string | null;
  title: string | null;
  title_zh: string | null;
  category: string | null;
  amazon_price_usd?: number | null;
  sell_price_usd?: number | null;
  fulfillment_method?: string | null;
  monthly_sales?: number | null;
  monthly_sales_estimate?: number | null;
  monthly_sales_estimate_min?: number | null;
  monthly_sales_estimate_max?: number | null;
  monthly_sales_confidence?: string | null;
  monthly_sales_source?: string | null;
  bsr?: number | null;
  reviews?: number | null;
  seller_count?: number | null;
  lithium_battery_warning?: boolean | null;
  fba_fee_usd?: number | null;
  package_weight_g?: number | null;
  package_length_mm?: number | null;
  package_width_mm?: number | null;
  package_height_mm?: number | null;
  weight_label?: string | null;
  dimensions_label?: string | null;
  relevance_status?: string | null;
  relevance_score?: number | null;
  relevance_should_process?: boolean | null;
  relevance_reason?: string | null;
  relevance_matched_terms?: string[];
  relevance_blocked_terms?: string[];
  supplier_name: string | null;
  supplier_url: string | null;
  supplier_platform?: string | null;
  supplier_platform_label?: string | null;
  supplier_url_type?: string | null;
  supplier_detail_url?: string | null;
  supplier_search_url?: string | null;
  supplier_search_pages?: RaSupplierSearchPage[];
  unit_price_cny: number | null;
  domestic_shipping_cny: number | null;
  supplier_total_cny: number | null;
  moq: number | null;
  one_piece_hint: boolean;
  pack_label?: string | null;
  pack_quantity?: number | null;
  supplier_pack_label?: string | null;
  quantity_cost_multiplier?: number | null;
  quantity_alignment_status?: string | null;
  quantity_alignment_reason?: string | null;
  suppliers?: Array<{
    supplier_name: string | null;
    supplier_title?: string | null;
    supplier_url: string | null;
    supplier_platform?: string | null;
    supplier_platform_label?: string | null;
    supplier_url_type?: string | null;
    supplier_detail_url?: string | null;
    supplier_search_url?: string | null;
    unit_price_cny: number | null;
    domestic_shipping_cny: number | null;
    supplier_total_cny: number | null;
    moq: number | null;
    verdict?: string | null;
    gross_margin?: number | null;
    gross_profit_usd?: number | null;
    gross_profit_cny?: number | null;
    snapshot_id?: string | null;
    is_lowest_price?: boolean | null;
    rating?: number | null;
    match_score?: number | null;
    offer_status?: string | null;
    crawler_status?: string | null;
    one_piece_hint?: boolean | null;
    supplier_alignment?: RaSupplierAlignment | null;
    match_reason?: string | null;
    shipping_notice?: string | null;
  }>;
  supplier_alignment?: RaSupplierAlignment | null;
  gross_profit_usd: number | null;
  gross_profit_cny: number | null;
  gross_margin: number | null;
  supplier_total_cny_min?: number | null;
  supplier_total_cny_max?: number | null;
  gross_profit_usd_min?: number | null;
  gross_profit_usd_max?: number | null;
  gross_profit_cny_min?: number | null;
  gross_profit_cny_max?: number | null;
  gross_margin_min?: number | null;
  gross_margin_max?: number | null;
  verdict: string | null;
  warnings: string[];
  blocked_reasons: string[];
  exchange_rate_usd_cny?: number | null;
  snapshot_id?: string | null;
  ai_selection?: RaAiSelectionResult | null;
};

export type RaSupplierSearchPage = {
  query?: string | null;
  platform?: string | null;
  platform_label?: string | null;
  search_url?: string | null;
  status?: string | null;
  result_count?: number | null;
};

export type RaSupplierAlignment = {
  match_status?: "match" | "review" | "mismatch" | string;
  match_score?: number | null;
  match_reason?: string | null;
  warnings?: string[];
  cost_multiplier?: number | null;
  raw_unit_price_cny?: number | null;
  adjusted_unit_price_cny?: number | null;
  quantity?: {
    status?: string | null;
    pending_kind?: string | null;
    amazon_pack_count?: number | null;
    amazon_pack_label?: string | null;
    supplier_pack_count?: number | null;
    supplier_pack_label?: string | null;
    cost_multiplier?: number | null;
    reason?: string | null;
  };
  dimensions?: {
    status?: string | null;
    reason?: string | null;
    cost_multiplier?: number | null;
    amazon_dimensions?: unknown[];
    supplier_dimensions?: unknown[];
  };
};

export type RaAutoProfitResult = {
  query: string;
  asin_limit: number;
  supplier_limit: number;
  exchange_rate: {
    usd_cny: number;
    source: string;
    live: boolean;
    fetched_at: string | null;
    warning: string | null;
  };
  matched_products: Array<{
    asin: string;
    title: string | null;
    title_zh: string | null;
    image_url: string | null;
    category: string | null;
    source_query: string | null;
    match_score: number | null;
    relevance_status?: string | null;
    relevance_score?: number | null;
    relevance_reason?: string | null;
  }>;
  supplier_runs: Array<{
    asin: string;
    candidate_id?: string | null;
    counts?: Record<string, number>;
    warnings?: string[];
  }>;
  items: RaAutoProfitItem[];
  items_page?: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_previous: boolean;
    has_next: boolean;
    search: string;
    category: string;
    verdict: string;
    sort: string;
    sort_direction: string;
  };
  counts: {
    matched_products: number;
    candidate_products?: number;
    selected_products?: number;
    processed_products: number;
    target_profit_pass?: number;
    max_products_per_job?: number;
    candidate_offers: number;
    priced_offers: number;
    profit_snapshots: number;
    profit_pass: number;
    profit_reject: number;
    profit_blocked: number;
    profit_quantity_pending?: number;
    ai_candidates?: number;
    ai_evaluations?: number;
    ai_pass?: number;
    ai_reject?: number;
    ai_review?: number;
    final_decisions?: number;
    reports?: number;
    mock_ai_enabled?: boolean;
    mock_ai_version?: string | null;
    rw_empty_result?: boolean;
    empty_reason?: string | null;
    empty_recommendation?: string | null;
    fatal_provider_error?: boolean;
  };
  formula: RaProfitFormula;
  warnings: string[];
};

export type RaAutoProfitJobItemsQuery = {
  item_page?: number;
  item_page_size?: number;
  item_search?: string;
  item_category?: string;
  item_verdict?: string;
  item_sort?: string;
  item_sort_direction?: string;
};

export type RaAutoProfitJobResult = RaAutoProfitResult & {
  run_id: string;
  status: "queued" | "running" | "completed" | "partial" | "failed" | string;
  runtime_mode: string | null;
  ai_selection?: {
    run_id: string;
    runtime_mode: string;
    mock: boolean;
    mock_pipeline_version: string;
    items: RaAiSelectionResult[];
    counts: {
      ai_candidates: number;
      ai_pass: number;
      ai_reject: number;
      ai_review: number;
      ai_evaluations: number;
      final_decisions: number;
      reports: number;
    };
  };
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};
