export type RwStatus = {
  active: boolean;
  endpoints: string[];
  mode: "mock_mode";
  mock_mode_active: boolean;
  module: "R-W";
  organization: string;
  r_a: {
    inactive: boolean;
    locked_until_rw_ready: boolean;
  };
  real_keepa_api_used: boolean;
  waiting_for_keys: boolean;
};

export type RwProduct = {
  asin: string;
  title: string;
  category: string;
  price: number;
  bsr: number;
  reviews: number;
  seller_count: number;
  state: string;
  rule_result: string;
  margin: number;
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
  mode: "mock_mode";
  organization: string;
};

export type RwRulesResponse = {
  count: number;
  enabled: boolean;
  items: RwRule[];
  mode: "mock_mode";
};

