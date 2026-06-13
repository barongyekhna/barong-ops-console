import type {
  ProductAiCanonicalFields,
  ProductValueMap,
} from "@/modules/k12/services/k12Api";

export type ProductRiskInput = Readonly<
  Omit<
    ProductAiCanonicalFields,
    "features" | "keywords" | "specs" | "dimensions"
  >
> & {
  readonly features: readonly string[];
  readonly keywords: readonly string[];
  readonly specs: Readonly<ProductValueMap>;
  readonly dimensions: Readonly<ProductValueMap>;
};

export type RiskFlagType =
  | "compliance"
  | "exaggeration"
  | "missing_info"
  | "category_risk";

export type RiskSeverity = "low" | "medium" | "high";

export type RiskField = "title" | "description" | "specs";

export type RiskSuggestionReason = "SEO" | "compliance" | "clarity";

export type ProductRiskFlag = {
  type: RiskFlagType;
  severity: RiskSeverity;
  field: RiskField;
  message: string;
};

export type ProductRiskSuggestion = {
  field: RiskField;
  suggestion: string;
  reason: RiskSuggestionReason;
};

export type ProductRiskAnalysis = {
  risk_score: number;
  compliance_score: number;
  seo_score: number;
  conversion_score: number;
  flags: ProductRiskFlag[];
  suggestions: ProductRiskSuggestion[];
};
