import {
  analyzeProductRisk as runLocalRiskEngine,
} from "../risk-engine";
import type { ProductRiskAnalysis, ProductRiskInput } from "../types";

export function analyzeProductRisk(
  product: ProductRiskInput,
): ProductRiskAnalysis {
  return runLocalRiskEngine(product);
}
