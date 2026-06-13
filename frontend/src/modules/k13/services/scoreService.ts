import { computeProductScore as runLocalScoringEngine } from "../scoring-engine";
import type {
  ProductRiskAnalysis,
  ProductRiskInput,
  ProductScoreOutput,
  ProductSuggestionOutput,
} from "../types";

export function computeProductScore(
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
  suggestions: ProductSuggestionOutput,
): ProductScoreOutput {
  return runLocalScoringEngine(product, riskAnalysis, suggestions);
}
