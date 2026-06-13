import {
  generateProductSuggestions as runLocalSuggestionEngine,
} from "../suggestion-engine";
import type {
  ProductRiskAnalysis,
  ProductRiskInput,
  ProductSuggestionOutput,
} from "../types";

export function generateProductSuggestions(
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
): ProductSuggestionOutput {
  return runLocalSuggestionEngine(product, riskAnalysis);
}
