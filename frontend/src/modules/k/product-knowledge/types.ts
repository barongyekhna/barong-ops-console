export type ProductReviewStatus =
  | "draft"
  | "ai_structured"
  | "needs_review"
  | "reviewed"
  | "approved"
  | "blocked"
  | "archived";

export type KCategoryTree = "google" | "amazon";

export type CategorySpecFieldTarget = "additional" | "standard";
export type CategorySpecFieldValueType = "number" | "text" | "enum" | "boolean";

export type CategorySpecField = {
  key: string;
  target: CategorySpecFieldTarget;
  label_zh: string;
  label_en: string;
  value_type: CategorySpecFieldValueType;
  unit: string | null;
  required: boolean;
  enum_options: string[] | null;
  hint_zh: string | null;
};

export type CategorySpecTemplate = {
  category_id: string;
  category_tree: KCategoryTree;
  status: "draft" | "approved";
  fields: CategorySpecField[];
  created_at?: string | null;
  updated_at?: string | null;
};

export type SpecPasteMatch = {
  value: unknown;
  raw_value: string;
  source_label: string;
};

export type SpecPasteParseResponse = {
  matched: Record<string, SpecPasteMatch>;
  unmatched_lines: string[];
  missing_required: string[];
};

export type ProductKnowledgeListItem = {
  id: string;
  product_key: string;
  sku: string | null;
  parent_sku?: string | null;
  main_keyword?: string | null;
  primary_keyword?: string | null;
  target_market?: string | null;
  product_name_en: string | null;
  brand_name: string | null;
  product_type: string | null;
  product_status: string;
  review_status: ProductReviewStatus | string;
  workspace_key: string;
  business_context: string;
  scope_mode: string;
  organization_name: string;
  variant_count?: number | null;
  variants?: ProductKnowledgeVariant[];
  created_at: string;
  updated_at: string;
};

export type ProductKnowledgeDetail = ProductKnowledgeListItem & {
  raw_input_text?: string | null;
  manufacturer?: string | null;
  short_description_en?: string | null;
  long_description_en?: string | null;
  primary_use_case_en?: string | null;
  target_customer_en?: string | null;
  attributes_count?: number | null;
  keywords_count?: number | null;
  risk_terms_count?: number | null;
  channel?: string | null;
  marketing_copy_json?: unknown;
  image_instruction_json?: unknown;
  marketing_copy_zh?: string | null;
  image_instruction_zh?: string | null;
  reference_image_url?: string | null;
  shipping_class?: string | null;
  shipping_review_needed?: boolean;
  shipping_assignment?: {
    rule_type?: string | null;
    used_kg?: number | null;
    review_reason?: string | null;
  } | null;
  contains_battery?: boolean;
  category_id?: string | null;
  category_tree?: KCategoryTree | null;
  category_path?: string | null;
  google_product_category?: string | null;
  amazon_category_id?: string | null;
  package_includes_json?: string[] | null;
  structured_specs_json?: Record<string, unknown> | null;
  specs_incomplete?: boolean;
  missing_required_specs?: string[];
  // 尺寸/重量:读模型 2026-09-04 起回传,供「基础档案」面板回填。
  dimensions_json?: Record<string, unknown> | null;
  weight_json?: Record<string, unknown> | null;
  package_dimensions_json?: Record<string, unknown> | null;
  package_weight_json?: Record<string, unknown> | null;
  selling_points_candidates_json?: Record<string, unknown> | null;
  selling_points_approved_json?: Record<string, unknown> | null;
  faq_research_json?: Record<string, unknown> | null;
};

export type WShippingClassOption = {
  id: string;
  slug: string;
  name: string;
  active: boolean;
};

export type ProductKnowledgeListResponse = {
  items: ProductKnowledgeListItem[];
  count: number;
  limit: number;
  offset: number;
};

export type ProductSectionState = {
  submitted: boolean;
  dirty: boolean;
  status: "submitted" | "pending" | "dirty" | "blocked";
  reason?: string | null;
  current_digest?: string | null;
  submitted_digest?: string | null;
  count: number;
  submitted_at?: string | null;
};

export type ProductReadinessState = {
  ready: boolean;
  keywords: ProductSectionState;
  images: ProductSectionState;
  selling_points: ProductSectionState;
};

export type ProductKeywordInput = {
  keyword_text: string;
  keyword_type: "primary" | "secondary" | "long_tail" | "b2b" | "negative" | "risk";
  language_code: string;
  market?: string | null;
  source?: string;
  status?: "candidate" | "approved" | "rejected" | "removed";
  reason?: string | null;
};

export type ProductKnowledgeCreatePayload = {
  raw_input_text: string;
  main_keyword: string;
  target_market: string;
  source_url?: string | null;
  reference_image_url?: string | null;
  reference_image_urls?: string[] | null;
  keywords?: ProductKeywordInput[];
  target_market_label?: string;
  target_locale?: string;
  parent_sku?: string | null;
  source_system?: string | null;
  source_record_id?: string | null;
  sku?: string | null;
  product_status?: string;
  review_status?: ProductReviewStatus;
  product_name_en?: string | null;
  brand_name?: string | null;
  manufacturer?: string | null;
  product_type: "simple_product" | "variable_product";
  regular_price?: number | null;
  price_currency?: string | null;
  dimensions_json?: Record<string, unknown> | null;
  weight_json?: Record<string, unknown> | null;
  package_includes_json?: string[] | null;
  structured_specs_json?: Record<string, unknown> | null;
  short_description_en?: string | null;
  long_description_en?: string | null;
  primary_use_case_en?: string | null;
  target_customer_en?: string | null;
  manual_notes?: string | null;
  variants?: ProductVariantInput[];
  attributes?: ProductKnowledgeAttributeInput[];
  channel?: string;
  category_id?: string | null;
  festival_style?: string | null;
};

export type ProductKnowledgeUpdatePayload = Partial<{
  review_status: ProductReviewStatus;
  product_name_en: string;
  package_includes_json: string[] | null;
  structured_specs_json: Record<string, unknown> | null;
  // 「基础档案」面板:类型只在变体行齐的情况下才允许裸 PATCH(后端 409 守卫),
  // 切类型请走 syncProductVariants。
  product_type: "simple_product" | "variable_product";
  dimensions_json: Record<string, unknown> | null;
  weight_json: Record<string, unknown> | null;
  package_dimensions_json: Record<string, unknown> | null;
  package_weight_json: Record<string, unknown> | null;
}>;

/** PUT /k/products/{id}/variants:带 variant_id 原地更新(sku 不变),不带 = 新建。 */
export type ProductVariantSyncItem = ProductVariantInput & {
  variant_id?: string | null;
};

export type ProductVariantsSyncPayload = {
  product_type: "simple_product" | "variable_product";
  variants: ProductVariantSyncItem[];
};

/** 一条参考图链接的落库结果,逐条回,不压扁。 */
export type ReferenceImageOutcome = {
  url: string;
  status: "stored" | "failed" | "skipped";
  variant_sku: string | null;
  asset_id: string | null;
  error: string | null;
};

export type ProductVariantsSyncResponse = {
  product: ProductKnowledgeDetail;
  reference_images: ReferenceImageOutcome[];
};

export type ProductReferenceImagesPayload = {
  urls: string[];
  variant_id?: string | null;
};

export type ProductReferenceImagesResponse = {
  product: ProductKnowledgeDetail;
  items: ReferenceImageOutcome[];
};

export type ProductCreateFormPayload = Omit<
  ProductKnowledgeCreatePayload,
  "target_market" | "target_market_label"
> & {
  target_locale: string;
  target_market: string;
  target_market_label: string;
};

export type ProductKnowledgeAttributeInput = {
  attribute_key: string;
  attribute_value_text?: string | null;
  attribute_value_json?: Record<string, unknown> | unknown[] | null;
  attribute_unit?: string | null;
  attribute_group?: string | null;
  source?: string | null;
  confidence?: number | null;
  requires_review?: boolean;
};

export type ProductDimensionsInput = {
  length: string;
  width: string;
  height: string;
  unit: "cm" | "inch";
};

export type ProductWeightInput = {
  value: string;
  unit: "kg" | "lb" | "g" | "oz";
};

export type ProductVariantInput = {
  color?: string | null;
  size?: string | null;
  function?: string | null;
  quantity?: number | null;
  price_override?: number | null;
  dimensions_json?: Record<string, unknown> | null;
  weight_json?: Record<string, unknown> | null;
  reference_image_url?: string | null;
  attributes?: Record<string, unknown>;
};

export type ProductVariantAttributeType = "size" | "color" | "function" | "quantity";

export type ProductVariantAttributeInput = {
  type: ProductVariantAttributeType;
  value: string;
};

export type ProductVariantFormInput = {
  attributes: ProductVariantAttributeInput[];
  price_override: string;
  dimensions_input: ProductDimensionsInput;
  weight_input: ProductWeightInput;
  reference_image_url: string;
};

export type ProductManualSpecInput = {
  label: string;
  value: string;
  unit: string;
};

export type ProductKnowledgeVariant = {
  id: string;
  product_id: string;
  parent_sku: string;
  variant_sku: string;
  variant_hash: string;
  color: string | null;
  size: string | null;
  function: string | null;
  quantity: number | null;
  price_override: number | null;
  attributes_json: Record<string, unknown> | unknown[] | null;
  image_folder: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ProductFormValues = {
  product_name_en: string;
  main_keyword: string;
  extra_keywords: string[];
  brand_name: string;
  source_url: string;
  reference_image_urls: string[];
  product_type: "simple_product" | "variable_product";
  price_value: string;
  price_currency: string;
  target_market: string;
  dimensions_input: ProductDimensionsInput;
  weight_input: ProductWeightInput;
  package_includes: string[];
  manual_specs: ProductManualSpecInput[];
  raw_input_text: string;
  variants: ProductVariantFormInput[];
  channel: string;
  category_id: string;
  category_label: string;
  festival_style: string;
};

export type KWorkflowStatus =
  | "created"
  | "running"
  | "blocked"
  | "failed"
  | "ready_for_export"
  | "exported"
  | string;

export type KWorkflowTraceItem = {
  step: string;
  status: string;
  timestamp: string;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  error?: Record<string, unknown> | null;
};

export type KWorkflowExecution = {
  id: string;
  product_id: string;
  organization_name: string;
  workspace_key: string;
  business_context: string;
  scope_mode: string;
  target_market: string;
  target_region: string | null;
  status: KWorkflowStatus;
  current_step: string;
  trace_json: KWorkflowTraceItem[];
  chatgpt_filter_result_json: Record<string, unknown> | null;
  claude_filter_result_json: {
    final_keywords?: string[];
    high_value_keywords?: string[];
    low_value_keywords?: string[];
    risk_keywords?: Array<string | { term?: string; reason?: string | null }>;
  } | null;
  risk_approval_log_json: Record<string, unknown> | null;
  final_keyword_set_json: {
    primary_keywords?: string[];
    secondary_keywords?: string[];
    longtail_keywords?: string[];
  } | null;
  unit_conversion_json: Record<string, unknown> | null;
  image_binding_json: Record<string, unknown> | null;
  export_payloads_json: Record<string, unknown> | null;
  execution_gate_logs_json: Array<Record<string, unknown>>;
  error_report_json: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type KWorkflowStartPayload = {
  target_market: string;
  target_region?: string | null;
  main_keyword?: string | null;
  serp_query?: string | null;
  seed_keywords?: string[];
  competitors?: string[];
};

export type KWorkflowControlPayload = {
  execution_id?: string | null;
  step?: string | null;
  workflow_payload?: KWorkflowStartPayload | null;
};

export type KRiskReviewDecision = {
  risk_term_id?: string | null;
  term: string;
  decision: "approve" | "reject";
  reason?: string | null;
};

export type KRiskReviewPayload = {
  execution_id?: string | null;
  decisions: KRiskReviewDecision[];
  confirm_no_risk_terms?: boolean;
};

export type KMediaAsset = {
  id: string;
  product_id: string;
  variant_sku: string | null;
  asset_type: string;
  asset_role: string;
  status: string;
  review_status: string;
  object_key: string | null;
  file_url_placeholder: string | null;
  file_url: string | null;
  thumbnail_url: string | null;
  preview_url: string | null;
  mime_type: string | null;
  width: number | null;
  height: number | null;
  file_size: number | null;
  source: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type KMediaListResponse = {
  items: KMediaAsset[];
  count: number;
};

export type KMediaCreatePayload = {
  product_id: string;
  variant_sku: string;
  asset_type: string;
  asset_role?: string;
  filename?: string | null;
  file_url_placeholder?: string | null;
  mime_type?: string | null;
  source?: string | null;
  metadata?: Record<string, unknown>;
};

export type KImportISystemImagePayload = {
  variant_id: string;
  source_type: "generate" | "edit";
  image_prompt_enhanced: string;
  prompt_original?: string | null;
  aspect_ratio?: string | null;
  style_config?: Record<string, unknown>;
  event_id?: string | null;
  images: Array<{
    image_base64: string;
    mime_type: string;
    width?: number | null;
    height?: number | null;
    content_sha256?: string | null;
    candidate_id?: string | null;
    metadata?: Record<string, unknown>;
  }>;
};

export type KImportISystemImageResponse = {
  status: "saved";
  product_id: string;
  variant_id: string;
  variant_sku: string;
  asset_ids: string[];
  submitted: boolean;
  submit_status: string;
  message?: string | null;
};

export type KWorkflowReport = {
  workflow_id: string;
  product_id: string;
  organization: string;
  status: string;
  current_step: string;
  full_pipeline_trace: KWorkflowTraceItem[];
  chatgpt_filter_result: Record<string, unknown> | null;
  claude_filter_result: Record<string, unknown> | null;
  risk_approval_log: Record<string, unknown> | null;
  final_keyword_set: Record<string, unknown> | null;
  export_payloads: Record<string, unknown> | null;
  execution_gate_logs: Array<Record<string, unknown>>;
  error_report: Record<string, unknown> | null;
};

export type KWorkflowExportResponse = {
  execution: KWorkflowExecution;
  report: KWorkflowReport;
};

/** 风险词的人工决策。没有第三种值——不点就是没审，不让提交。 */
export type RiskDecisionValue = "approve" | "reject";
