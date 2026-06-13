import type { ProductRiskAnalysis, ProductRiskInput } from "./risk";
import type { ProductSuggestionOutput } from "./suggestion";

export type ProductHealthLevel =
  | "excellent"
  | "good"
  | "medium"
  | "poor"
  | "critical";

export type ProductScoreInsightType = "risk" | "opportunity" | "warning";

export type ProductScoreBreakdown = {
  risk_weight: number;
  seo_weight: number;
  conversion_weight: number;
  compliance_weight: number;
};

export type ProductScoreInsight = {
  type: ProductScoreInsightType;
  message: string;
};

export type ProductScoreOutput = {
  overall_score: number;
  risk_score: number;
  compliance_score: number;
  seo_score: number;
  conversion_score: number;
  health_level: ProductHealthLevel;
  breakdown: ProductScoreBreakdown;
  insights: ProductScoreInsight[];
};

export type ComputeProductScore = (
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
  suggestions: ProductSuggestionOutput,
) => ProductScoreOutput;
