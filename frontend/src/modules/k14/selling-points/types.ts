export type BulletCategory = "feature" | "benefit" | "usage" | "spec";

export type SellingPointSource =
  | "k13_ai_engine"
  | "k13_bridge"
  | "manual_input"
  | "future_live_ai";

export type BulletPoint = {
  text: string;
  category: BulletCategory;
  importance_score: number;
};

export type ProductSellingPoints = {
  product_id: string;
  title: string;
  raw_input: string;
  language: string;
  bullets: BulletPoint[];
  seo_bullets: string[];
  seo_keywords: string[];
  market_tags: string[];
  source: SellingPointSource;
  confidence_score: number;
};
