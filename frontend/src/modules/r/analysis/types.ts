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
  category: string | null;
  sell_price_usd: number | null;
  landed_cost_usd: number | null;
  amazon_fees_usd: number | null;
  gross_profit_usd: number | null;
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
    unit_price_cny?: number | null;
    domestic_shipping_cny?: number | null;
    moq?: number | null;
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
    status: string;
    result_count: number;
  }>;
  offers: Array<{
    offer_id: string;
    search_id: string;
    supplier_name: string | null;
    supplier_url: string | null;
    unit_price_cny: number | null;
    domestic_shipping_cny: number | null;
    moq: number | null;
    match_score: number | null;
    offer_status: string;
    crawler_status: string;
    warning: string | null;
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
