export type ProductReviewStatus =
  | "draft"
  | "ai_structured"
  | "needs_review"
  | "reviewed"
  | "approved"
  | "blocked"
  | "archived";

export type ProductKnowledgeListItem = {
  id: string;
  product_key: string;
  sku: string | null;
  product_name_en: string | null;
  brand_name: string | null;
  product_type: string | null;
  product_status: string;
  review_status: ProductReviewStatus | string;
  canonical_language: string;
  workspace_key: string;
  business_context: string;
  scope_mode: string;
  created_at: string;
  updated_at: string;
};

export type ProductKnowledgeDetail = ProductKnowledgeListItem & {
  raw_input_text?: string | null;
  raw_input_language?: string | null;
  manufacturer?: string | null;
  short_description_en?: string | null;
  long_description_en?: string | null;
  primary_use_case_en?: string | null;
  target_customer_en?: string | null;
  attributes_count?: number | null;
  keywords_count?: number | null;
  risk_terms_count?: number | null;
};

export type ProductKnowledgeListResponse = {
  items: ProductKnowledgeListItem[];
  count: number;
  limit: number;
  offset: number;
};

export type ProductKnowledgeCreatePayload = {
  product_key: string;
  raw_input_text: string;
  raw_input_language: string;
  source_system?: string | null;
  source_record_id?: string | null;
  sku?: string | null;
  product_status?: string;
  review_status?: ProductReviewStatus;
  canonical_language?: string;
  product_name_en?: string | null;
  brand_name?: string | null;
  manufacturer?: string | null;
  product_type?: string | null;
  short_description_en?: string | null;
  long_description_en?: string | null;
  primary_use_case_en?: string | null;
  target_customer_en?: string | null;
  manual_notes?: string | null;
};

export type ProductFormValues = {
  product_key: string;
  product_name_en: string;
  sku: string;
  brand_name: string;
  product_type: string;
  raw_input_language: string;
  raw_input_text: string;
};
