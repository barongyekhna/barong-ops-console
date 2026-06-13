import type {
  ProductHealthLevel,
  ProductRiskAnalysis,
  ProductRiskInput,
  ProductScoreBreakdown,
  ProductScoreInsight,
  ProductScoreOutput,
  ProductSuggestionItem,
  ProductSuggestionOutput,
} from "../types";

type AreaScore = {
  label: string;
  score: number;
};

type RankedSuggestion = {
  area: string;
  suggestion: ProductSuggestionItem;
};

const scoreBreakdown: ProductScoreBreakdown = {
  risk_weight: 0.35,
  seo_weight: 0.25,
  conversion_weight: 0.25,
  compliance_weight: 0.15,
};

export function computeProductScore(
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
  suggestions: ProductSuggestionOutput,
): ProductScoreOutput {
  const riskScore = clampScore(riskAnalysis.risk_score);
  const complianceScore = aggregateStrategyScore(
    riskAnalysis.compliance_score,
    suggestions.strategy_scores.compliance_strategy,
    0.78,
  );
  const seoScore = aggregateStrategyScore(
    riskAnalysis.seo_score,
    suggestions.strategy_scores.seo_strategy,
    0.7,
  );
  const conversionScore = aggregateStrategyScore(
    riskAnalysis.conversion_score,
    suggestions.strategy_scores.conversion_strategy,
    0.7,
  );
  const overallScore = clampScore(
    (100 - riskScore) * scoreBreakdown.risk_weight +
      seoScore * scoreBreakdown.seo_weight +
      conversionScore * scoreBreakdown.conversion_weight +
      complianceScore * scoreBreakdown.compliance_weight,
  );
  const healthLevel = calculateHealthLevel(
    overallScore,
    riskScore,
    complianceScore,
  );

  return {
    overall_score: overallScore,
    risk_score: riskScore,
    compliance_score: complianceScore,
    seo_score: seoScore,
    conversion_score: conversionScore,
    health_level: healthLevel,
    breakdown: { ...scoreBreakdown },
    insights: buildInsights(product, riskAnalysis, suggestions, {
      risk: riskScore,
      compliance: complianceScore,
      seo: seoScore,
      conversion: conversionScore,
      overall: overallScore,
    }),
  };
}

export default computeProductScore;

function aggregateStrategyScore(
  sourceScore: number,
  strategyScore: number,
  sourceWeight: number,
) {
  return clampScore(sourceScore * sourceWeight + strategyScore * (1 - sourceWeight));
}

function calculateHealthLevel(
  overallScore: number,
  riskScore: number,
  complianceScore: number,
): ProductHealthLevel {
  if (overallScore < 40 || riskScore >= 85 || complianceScore < 35) {
    return "critical";
  }

  if (overallScore < 55 || riskScore >= 70 || complianceScore < 50) {
    return "poor";
  }

  if (overallScore < 70 || riskScore >= 45) {
    return "medium";
  }

  if (overallScore < 85) {
    return "good";
  }

  return "excellent";
}

function buildInsights(
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
  suggestions: ProductSuggestionOutput,
  scores: {
    risk: number;
    compliance: number;
    seo: number;
    conversion: number;
    overall: number;
  },
): ProductScoreInsight[] {
  const insights: ProductScoreInsight[] = [];
  const highSeverityFlags = riskAnalysis.flags.filter(
    (flag) => flag.severity === "high",
  );
  const mediumSeverityFlags = riskAnalysis.flags.filter(
    (flag) => flag.severity === "medium",
  );
  const missingBasics = getMissingBasicFields(product);
  const weakestArea = getWeakestArea([
    { label: "compliance", score: scores.compliance },
    { label: "SEO", score: scores.seo },
    { label: "conversion", score: scores.conversion },
  ]);
  const topSuggestion = getTopSuggestion(suggestions);

  if (highSeverityFlags.length > 0 || scores.risk >= 70) {
    insights.push({
      type: "risk",
      message: `Risk review is required before publishing: ${formatRiskSummary(
        highSeverityFlags.length,
        mediumSeverityFlags.length,
      )}.`,
    });
  } else if (mediumSeverityFlags.length > 0 || scores.risk >= 40) {
    insights.push({
      type: "warning",
      message: `Moderate risk pressure remains: ${formatRiskSummary(
        highSeverityFlags.length,
        mediumSeverityFlags.length,
      )}.`,
    });
  }

  if (scores.compliance < 70) {
    insights.push({
      type: "risk",
      message:
        "Compliance readiness is below target; resolve claim, category, or evidence gaps first.",
    });
  }

  if (weakestArea.score < 72) {
    insights.push({
      type: "warning",
      message: `${capitalize(weakestArea.label)} is the weakest scoring area at ${weakestArea.score}.`,
    });
  }

  if (missingBasics.length > 0) {
    insights.push({
      type: "warning",
      message: `Canonical product data is missing ${joinList(missingBasics)}.`,
    });
  }

  if (topSuggestion) {
    insights.push({
      type: "opportunity",
      message: `${capitalize(
        topSuggestion.area,
      )} has the highest suggestion upside at ${clampScore(
        topSuggestion.suggestion.impact_score,
      )}.`,
    });
  } else if (scores.overall >= 85 && scores.risk <= 20) {
    insights.push({
      type: "opportunity",
      message:
        "Product health is strong; prioritize incremental SEO and conversion tuning.",
    });
  }

  return uniqueInsights(insights).slice(0, 5);
}

function getMissingBasicFields(product: ProductRiskInput) {
  return [
    normalizeText(product.title) ? "" : "title",
    normalizeText(product.description) ? "" : "description",
    product.features.length > 0 ? "" : "features",
    Object.keys(product.specs).length > 0 ? "" : "specs",
  ].filter(Boolean);
}

function getWeakestArea(areaScores: AreaScore[]) {
  return [...areaScores].sort((left, right) => left.score - right.score)[0];
}

function getTopSuggestion(
  suggestions: ProductSuggestionOutput,
): RankedSuggestion | null {
  const rankedSuggestions: RankedSuggestion[] = [
    ...suggestions.title_suggestions.map((suggestion) => ({
      area: "title",
      suggestion,
    })),
    ...suggestions.description_suggestions.map((suggestion) => ({
      area: "description",
      suggestion,
    })),
    ...suggestions.bullet_suggestions.map((suggestion) => ({
      area: "bullet content",
      suggestion,
    })),
  ].sort(
    (left, right) => right.suggestion.impact_score - left.suggestion.impact_score,
  );

  return rankedSuggestions[0] ?? null;
}

function formatRiskSummary(highCount: number, mediumCount: number) {
  if (highCount > 0 && mediumCount > 0) {
    return `${highCount} high and ${mediumCount} medium severity flags`;
  }

  if (highCount > 0) {
    return `${highCount} high severity flags`;
  }

  if (mediumCount > 0) {
    return `${mediumCount} medium severity flags`;
  }

  return "risk score is elevated";
}

function uniqueInsights(insights: ProductScoreInsight[]) {
  const seen = new Set<string>();

  return insights.filter((insight) => {
    const key = `${insight.type}:${insight.message.toLowerCase()}`;

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function joinList(items: string[]) {
  if (items.length <= 1) {
    return items[0] ?? "";
  }

  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function normalizeText(value: string) {
  return value.trim();
}

function clampScore(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.min(100, Math.max(0, Math.round(value)));
}
