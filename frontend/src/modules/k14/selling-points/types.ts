export type BulletCategory = "feature" | "benefit" | "usage" | "spec" | string;

export type SellingPointSource =
  | "k13_ai_engine"
  | "k13_bridge"
  | "manual_input"
  | "future_live_ai"
  | string;

export type BulletPoint = {
  id?: string | null;
  text: string;
  // 逐条中文对照(生成后由 DeepSeek 翻译填充,双语展示用)
  text_zh?: string | null;
  category: BulletCategory;
  importance_score: number;
  evidence?: string | null;
  evidence_excerpt?: string | null;
  verification_status?: "verified" | "unverified";
  review_decision?: "candidate" | "approve" | "edit" | "reject";
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
  marketing_copy?: string | null;
  translated_version?: string | null;
  chinese_translation?: string | null;
  target_language?: string | null;
  stored_event_id?: string | null;
};
