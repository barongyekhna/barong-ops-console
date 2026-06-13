import type { ProductRiskAnalysis, ProductRiskInput } from "./risk";

export type ProductSuggestionInput = ProductRiskInput;

export type ProductSuggestionReason =
  | "SEO"
  | "clarity"
  | "conversion"
  | "conversion improvement"
  | "readability / SEO"
  | "compliance";

export type ProductSuggestionItem = {
  suggestion: string;
  reason: ProductSuggestionReason;
  impact_score: number;
};

export type ProductStrategyScores = {
  seo_strategy: number;
  conversion_strategy: number;
  compliance_strategy: number;
};

export type ProductSuggestionOutput = {
  title_suggestions: ProductSuggestionItem[];
  description_suggestions: ProductSuggestionItem[];
  bullet_suggestions: ProductSuggestionItem[];
  seo_keywords: string[];
  strategy_scores: ProductStrategyScores;
};

export type GenerateProductSuggestions = (
  product: ProductSuggestionInput,
  riskAnalysis: ProductRiskAnalysis,
) => ProductSuggestionOutput;
