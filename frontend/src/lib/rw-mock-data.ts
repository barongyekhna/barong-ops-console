export const R_SERIES_TARGET_ORGANIZATION =
  "涌龙麟（深圳）国际贸易有限公司";

export const rwMockProducts = [
  {
    asin: "B033B3F98C",
    title: "Portable Door Draft Stopper",
    category: "Home & Kitchen",
    price: 34.99,
    bsr: 8421,
    reviews: 214,
    seller_count: 7,
    state: "rule_passed",
    rule_result: "rule_passed",
    margin: 0.4928,
    source: "mock_keepa",
  },
] as const;

export const rwRules = [
  {
    id: "price_band_filter",
    label: "price band filter",
    enabled: true,
    result: "passed",
    threshold: "25 <= price <= 70",
  },
  {
    id: "margin_check",
    label: "margin check",
    enabled: true,
    result: "passed",
    threshold: "est_net_margin >= 0.15",
  },
  {
    id: "competition_filter",
    label: "competition filter",
    enabled: true,
    result: "passed",
    threshold: "seller_count <= 15",
  },
  {
    id: "brand_dominance_filter",
    label: "brand dominance filter",
    enabled: true,
    result: "passed",
    threshold: "brand_share <= 0.50",
  },
  {
    id: "price_trend_filter",
    label: "price trend filter",
    enabled: true,
    result: "passed",
    threshold: "price_trend not declining",
  },
] as const;

export function rwStatusPayload() {
  return {
    active: true,
    endpoints: ["/api/rw/products", "/api/rw/status", "/api/rw/rules"],
    mode: "mock_mode",
    mock_mode_active: true,
    module: "R-W",
    organization: R_SERIES_TARGET_ORGANIZATION,
    r_a: {
      inactive: true,
      locked_until_rw_ready: true,
    },
    real_keepa_api_used: false,
    waiting_for_keys: true,
  };
}

export function rwProductsPayload() {
  return {
    count: rwMockProducts.length,
    items: rwMockProducts,
    mode: "mock_mode",
    organization: R_SERIES_TARGET_ORGANIZATION,
  };
}

export function rwRulesPayload() {
  return {
    count: rwRules.length,
    enabled: true,
    items: rwRules,
    mode: "mock_mode",
  };
}

