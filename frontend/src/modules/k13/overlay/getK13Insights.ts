import {
  analyzeProductRisk,
  computeProductScore,
  generateProductSuggestions,
} from "../services";
import type {
  ProductRiskAnalysis,
  ProductRiskInput,
  ProductScoreOutput,
  ProductSuggestionOutput,
} from "../types";

export type K13Insights = {
  risk: ProductRiskAnalysis;
  suggestions: ProductSuggestionOutput;
  score: ProductScoreOutput;
};

export function getK13Insights(product: ProductRiskInput): K13Insights {
  const risk = analyzeProductRisk(product);
  const suggestions = generateProductSuggestions(product, risk);
  const score = computeProductScore(product, risk, suggestions);

  return {
    risk,
    suggestions,
    score,
  };
}
