import type {
  ProductRiskAnalysis,
  ProductRiskFlag,
  ProductRiskInput,
  RiskField,
} from "../types/risk";
import type {
  ProductSuggestionItem,
  ProductSuggestionOutput,
  ProductStrategyScores,
} from "../types/suggestion";

type NormalizedProduct = {
  title: string;
  description: string;
  features: string[];
  keywords: string[];
  specs: Record<string, string>;
  dimensions: Record<string, string>;
  weight: string;
  minimumAgeYears: number | null;
  dishwasherSafe: boolean;
  allText: string;
};

const maxTitleLength = 92;
const maxDescriptionLength = 520;
const maxSuggestionCount = 3;
const maxKeywordCount = 12;

export function generateProductSuggestions(
  product: ProductRiskInput,
  riskAnalysis: ProductRiskAnalysis,
): ProductSuggestionOutput {
  const normalized = normalizeProduct(product);
  const seoKeywords = buildSeoKeywords(normalized);
  const titleSuggestions = uniqueSuggestionItems(
    buildTitleSuggestions(normalized, riskAnalysis, seoKeywords),
  ).slice(0, maxSuggestionCount);
  const descriptionSuggestions = uniqueSuggestionItems(
    buildDescriptionSuggestions(normalized, riskAnalysis),
  ).slice(0, maxSuggestionCount);
  const bulletSuggestions = uniqueSuggestionItems(
    buildBulletSuggestions(normalized, riskAnalysis),
  ).slice(0, maxSuggestionCount);

  return {
    title_suggestions: titleSuggestions,
    description_suggestions: descriptionSuggestions,
    bullet_suggestions: bulletSuggestions,
    seo_keywords: seoKeywords,
    strategy_scores: calculateStrategyScores(
      normalized,
      riskAnalysis,
      seoKeywords,
    ),
  };
}

export default generateProductSuggestions;

function buildTitleSuggestions(
  product: NormalizedProduct,
  riskAnalysis: ProductRiskAnalysis,
  seoKeywords: string[],
): ProductSuggestionItem[] {
  const optimizedTitle = buildOptimizedTitle(product);
  const keywordTitle = buildKeywordTitle(product, seoKeywords);
  const riskTitleSuggestion = getRiskSuggestion(riskAnalysis, "title");
  const titleFlagCount = countFlags(riskAnalysis.flags, "title");
  const impactScore = impactFromGap(riskAnalysis.seo_score, 42, titleFlagCount);

  return [
    optimizedTitle
      ? suggestionItem(optimizedTitle, "SEO", impactScore)
      : null,
    keywordTitle && keywordTitle !== optimizedTitle
      ? suggestionItem(
          keywordTitle,
          "clarity",
          impactFromGap(riskAnalysis.seo_score, 34, titleFlagCount),
        )
      : null,
    riskTitleSuggestion && riskTitleSuggestion !== optimizedTitle
      ? suggestionItem(
          riskTitleSuggestion,
          "SEO",
          impactFromGap(riskAnalysis.seo_score, 30, titleFlagCount),
        )
      : null,
  ].filter(isSuggestionItem);
}

function buildDescriptionSuggestions(
  product: NormalizedProduct,
  riskAnalysis: ProductRiskAnalysis,
): ProductSuggestionItem[] {
  const optimizedDescription = buildOptimizedDescription(product);
  const conciseDescription = buildConciseDescription(product);
  const riskDescriptionSuggestion = getRiskSuggestion(riskAnalysis, "description");
  const descriptionFlagCount = countFlags(riskAnalysis.flags, "description");
  const impactScore = impactFromGap(
    riskAnalysis.conversion_score,
    44,
    descriptionFlagCount,
  );

  return [
    optimizedDescription
      ? suggestionItem(
          optimizedDescription,
          "conversion improvement",
          impactScore,
        )
      : null,
    conciseDescription && conciseDescription !== optimizedDescription
      ? suggestionItem(
          conciseDescription,
          "clarity",
          impactFromGap(
            riskAnalysis.conversion_score,
            34,
            descriptionFlagCount,
          ),
        )
      : null,
    riskDescriptionSuggestion &&
    riskDescriptionSuggestion !== optimizedDescription
      ? suggestionItem(
          riskDescriptionSuggestion,
          "clarity",
          impactFromGap(
            riskAnalysis.conversion_score,
            30,
            descriptionFlagCount,
          ),
        )
      : null,
  ].filter(isSuggestionItem);
}

function buildBulletSuggestions(
  product: NormalizedProduct,
  riskAnalysis: ProductRiskAnalysis,
): ProductSuggestionItem[] {
  const suggestions: ProductSuggestionItem[] = [];
  const bulletImpact = impactFromGap(
    Math.min(riskAnalysis.conversion_score, riskAnalysis.seo_score),
    38,
    countFlags(riskAnalysis.flags, "specs"),
  );
  const primaryBullet = buildPrimaryBullet(product);
  const factBullet = buildFactBullet(product);
  const careBullet = buildCareBullet(product);
  const specRiskSuggestion = getRiskSuggestion(riskAnalysis, "specs");

  if (primaryBullet) {
    suggestions.push(
      suggestionItem(primaryBullet, "readability / SEO", bulletImpact),
    );
  }

  if (factBullet && factBullet !== primaryBullet) {
    suggestions.push(
      suggestionItem(
        factBullet,
        "conversion",
        impactFromGap(riskAnalysis.conversion_score, 34, 0),
      ),
    );
  }

  if (careBullet && careBullet !== primaryBullet && careBullet !== factBullet) {
    suggestions.push(
      suggestionItem(
        careBullet,
        "clarity",
        impactFromGap(riskAnalysis.conversion_score, 28, 0),
      ),
    );
  }

  if (specRiskSuggestion) {
    suggestions.push(
      suggestionItem(
        specRiskSuggestion,
        "compliance",
        impactFromGap(
          riskAnalysis.compliance_score,
          36,
          countComplianceFlags(riskAnalysis.flags),
        ),
      ),
    );
  }

  return suggestions;
}

function buildOptimizedTitle(product: NormalizedProduct) {
  const cleanedTitle = removeRiskyMarketingPhrases(product.title);
  const fallbackTitle = inferTitle(product);
  const baseTitle = cleanedTitle || fallbackTitle;
  const material = getSpecValue(product, ["material", "materials", "composition"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const lidType = getSpecValue(product, ["lid_type", "lid type", "lid"]);
  const additions = [
    capacity && !hasMeasurement(baseTitle) ? capacity : "",
    material && !containsAnyToken(baseTitle, tokenize(material)) ? material : "",
    lidType && !containsAnyToken(baseTitle, tokenize(lidType))
      ? `${lidType} lid`
      : "",
  ].filter(Boolean);
  const title = [baseTitle, ...additions].filter(Boolean).join(", ");

  return limitText(title || fallbackTitle, maxTitleLength);
}

function buildKeywordTitle(product: NormalizedProduct, seoKeywords: string[]) {
  const productType = inferProductType(product);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const material = getSpecValue(product, ["material", "materials", "composition"]);
  const audience = isChildFacingProduct(product) ? "Kids" : "";
  const keyword = seoKeywords.find((value) =>
    value.includes(productType.toLowerCase()),
  );
  const title = [
    capacity,
    material,
    audience,
    productType,
    keyword && !keyword.includes(productType.toLowerCase()) ? keyword : "",
  ]
    .filter(Boolean)
    .join(" ");

  return limitText(title || buildOptimizedTitle(product), maxTitleLength);
}

function buildOptimizedDescription(product: NormalizedProduct) {
  const title = buildOptimizedTitle(product) || inferTitle(product);
  const cleanedDescription = removeRiskyMarketingPhrases(product.description);
  const useCase = inferUseCase(product);
  const details = buildProductDetails(product);
  const baseSentence =
    cleanedDescription.length >= 90
      ? cleanedDescription
      : `${title} is designed for ${useCase}.`;
  const detailSentence =
    details.length > 0
      ? `Product details include ${details.join(", ")}.`
      : "Add reviewed material, size, care, and use details before publishing.";
  const featureSentence = buildFeatureSentence(product);
  const description = [baseSentence, featureSentence, detailSentence]
    .filter(Boolean)
    .join(" ");

  return limitText(description, maxDescriptionLength);
}

function buildConciseDescription(product: NormalizedProduct) {
  const title = buildOptimizedTitle(product) || inferTitle(product);
  const useCase = inferUseCase(product);
  const details = buildProductDetails(product).slice(0, 3);
  const detailText =
    details.length > 0 ? ` with ${details.join(", ")}` : "";

  return limitText(`${title} for ${useCase}${detailText}.`, 240);
}

function buildPrimaryBullet(product: NormalizedProduct) {
  const title = buildOptimizedTitle(product) || inferTitle(product);
  const feature = product.features
    .map(removeRiskyMarketingPhrases)
    .find((value) => value.length > 0);

  if (feature) {
    return limitText(`${feature} for ${inferUseCase(product)}.`, 180);
  }

  return limitText(`${title} for ${inferUseCase(product)}.`, 180);
}

function buildFactBullet(product: NormalizedProduct) {
  const details = buildProductDetails(product).slice(0, 4);

  if (details.length === 0) {
    return "Add a reviewed material, capacity, dimensions, or weight fact before publishing a feature bullet.";
  }

  return limitText(`Product facts: ${details.join(", ")}.`, 180);
}

function buildCareBullet(product: NormalizedProduct) {
  const ageText =
    product.minimumAgeYears !== null && product.minimumAgeYears > 0
      ? `Recommended for ages ${product.minimumAgeYears}+.`
      : "";
  const dishwasherText = product.dishwasherSafe
    ? "Dishwasher-safe according to current canonical care status."
    : "Hand wash recommended according to current canonical care status.";
  const dimensions = formatDimensions(product.dimensions);
  const weight = product.weight ? `Weight: ${product.weight}.` : "";

  return [ageText, dishwasherText, dimensions, weight]
    .filter(Boolean)
    .join(" ");
}

function buildSeoKeywords(product: NormalizedProduct) {
  const productType = inferProductType(product);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const material = getSpecValue(product, ["material", "materials", "composition"]);
  const lidType = getSpecValue(product, ["lid_type", "lid type", "lid"]);
  const audience = isChildFacingProduct(product) ? "kids" : "";
  const useCase = inferUseCase(product);
  const candidates = [
    ...product.keywords,
    [audience, productType].filter(Boolean).join(" "),
    [material, productType].filter(Boolean).join(" "),
    [capacity, productType].filter(Boolean).join(" "),
    [lidType, productType].filter(Boolean).join(" "),
    isInsulatedProduct(product) ? `insulated ${productType}` : "",
    useCase.includes("school") ? `school ${productType}` : "",
    productType,
    material,
    capacity,
  ];

  return uniqueStrings(
    candidates
      .map(normalizeKeyword)
      .filter((value) => value.length > 0 && !isComplianceSensitiveKeyword(value)),
  ).slice(0, maxKeywordCount);
}

function calculateStrategyScores(
  product: NormalizedProduct,
  riskAnalysis: ProductRiskAnalysis,
  seoKeywords: string[],
): ProductStrategyScores {
  const seoReadiness = clampScore(
    46 +
      Math.min(seoKeywords.length, 8) * 5 +
      (product.title.length >= 35 && product.title.length <= 90 ? 10 : 0) +
      (hasMeasurement(product.title) ? 6 : 0),
  );
  const conversionReadiness = clampScore(
    42 +
      Math.min(product.features.length, 4) * 7 +
      Math.min(buildProductDetails(product).length, 6) * 5 +
      (product.description.length >= 90 ? 8 : 0),
  );
  const complianceReadiness = clampScore(
    100 -
      riskAnalysis.flags.reduce((total, flag) => {
        if (flag.type === "compliance") {
          return total + severityPenalty(flag.severity, 1.1);
        }

        if (flag.type === "category_risk") {
          return total + severityPenalty(flag.severity, 0.85);
        }

        if (flag.type === "exaggeration") {
          return total + severityPenalty(flag.severity, 0.45);
        }

        return total;
      }, 0),
  );

  return {
    seo_strategy: blendScore(riskAnalysis.seo_score, seoReadiness, 0.68),
    conversion_strategy: blendScore(
      riskAnalysis.conversion_score,
      conversionReadiness,
      0.65,
    ),
    compliance_strategy: blendScore(
      riskAnalysis.compliance_score,
      complianceReadiness,
      0.8,
    ),
  };
}

function normalizeProduct(product: ProductRiskInput): NormalizedProduct {
  const title = normalizeText(product.title);
  const description = normalizeText(product.description);
  const features = normalizeStringArray(product.features);
  const keywords = normalizeStringArray(product.keywords);
  const specs = normalizeStringMap(product.specs);
  const dimensions = normalizeStringMap(product.dimensions);
  const weight = normalizeText(product.weight);
  const minimumAgeYears = Number.isFinite(product.minimum_age_years)
    ? product.minimum_age_years
    : null;
  const dishwasherSafe = Boolean(product.dishwasher_safe);
  const allText = [
    title,
    description,
    ...features,
    ...keywords,
    mapToSearchText(specs),
    mapToSearchText(dimensions),
    weight,
    minimumAgeYears !== null ? `minimum age ${minimumAgeYears}` : "",
    dishwasherSafe ? "dishwasher safe" : "not dishwasher safe",
  ]
    .join(" ")
    .toLowerCase();

  return {
    title,
    description,
    features,
    keywords,
    specs,
    dimensions,
    weight,
    minimumAgeYears,
    dishwasherSafe,
    allText,
  };
}

function buildProductDetails(product: NormalizedProduct) {
  const material = getSpecValue(product, ["material", "materials", "composition"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const lidType = getSpecValue(product, ["lid_type", "lid type", "lid"]);
  const dimensions = formatDimensions(product.dimensions);
  const ageText =
    product.minimumAgeYears !== null && product.minimumAgeYears > 0
      ? `ages ${product.minimumAgeYears}+`
      : "";

  return [
    material,
    capacity ? `${capacity} capacity` : "",
    lidType ? `${lidType} lid` : "",
    dimensions,
    product.weight ? `${product.weight} weight` : "",
    ageText,
  ].filter(Boolean);
}

function buildFeatureSentence(product: NormalizedProduct) {
  const features = product.features
    .map(removeRiskyMarketingPhrases)
    .filter(Boolean)
    .slice(0, 2);

  if (features.length === 0) {
    return "";
  }

  return `Key features include ${features.join(" and ")}.`;
}

function getRiskSuggestion(
  riskAnalysis: ProductRiskAnalysis,
  field: RiskField,
) {
  return riskAnalysis.suggestions.find((item) => item.field === field)
    ?.suggestion;
}

function suggestionItem(
  suggestion: string,
  reason: ProductSuggestionItem["reason"],
  impactScore: number,
): ProductSuggestionItem {
  return {
    suggestion: normalizeText(suggestion),
    reason,
    impact_score: clampScore(impactScore),
  };
}

function isSuggestionItem(
  item: ProductSuggestionItem | null,
): item is ProductSuggestionItem {
  return item !== null && item.suggestion.length > 0;
}

function uniqueSuggestionItems(items: ProductSuggestionItem[]) {
  const seen = new Set<string>();

  return items.filter((item) => {
    const key = normalizeText(item.suggestion).toLowerCase();

    if (!key || seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function getSpecValue(product: NormalizedProduct, keys: string[]) {
  const normalizedKeys = keys.map(normalizeSpecKey);
  const matchedEntry = Object.entries(product.specs).find(([key, value]) => {
    const normalizedKey = normalizeSpecKey(key);

    return (
      value.length > 0 &&
      normalizedKeys.some(
        (expectedKey) =>
          normalizedKey === expectedKey || normalizedKey.includes(expectedKey),
      )
    );
  });

  return matchedEntry?.[1] ?? "";
}

function inferTitle(product: NormalizedProduct) {
  const material = getSpecValue(product, ["material", "materials", "composition"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const audience = isChildFacingProduct(product) ? "Kids" : "";

  return [material, audience, inferProductType(product), capacity]
    .filter(Boolean)
    .join(" ");
}

function inferProductType(product: NormalizedProduct) {
  const typePatterns: Array<[RegExp, string]> = [
    [/\bwater bottle\b/i, "Water Bottle"],
    [/\bbottle\b/i, "Bottle"],
    [/\btumbler\b/i, "Tumbler"],
    [/\bmug\b/i, "Mug"],
    [/\bcharger\b/i, "Charger"],
    [/\blamp\b/i, "Lamp"],
    [/\btoy\b/i, "Toy"],
    [/\bbag\b/i, "Bag"],
    [/\bcontainer\b/i, "Container"],
  ];
  const matched = typePatterns.find(([expression]) =>
    expression.test(product.allText),
  );

  return matched?.[1] ?? "Product";
}

function inferUseCase(product: NormalizedProduct) {
  if (/\b(?:school|lunch|children|kids)\b/i.test(product.allText)) {
    return "school, lunches, and everyday use";
  }

  if (/\b(?:travel|trip|commute|outdoor|camp)\b/i.test(product.allText)) {
    return "travel and everyday use";
  }

  if (/\b(?:office|desk|work)\b/i.test(product.allText)) {
    return "workday and everyday use";
  }

  return "everyday use";
}

function formatDimensions(dimensions: Record<string, string>) {
  const entries = Object.entries(dimensions);

  if (entries.length === 0) {
    return "";
  }

  return entries
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`)
    .join(", ");
}

function normalizeText(value: string | number | boolean | null | undefined) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value).replace(/\s+/g, " ").trim();
}

function normalizeStringArray(values: readonly string[] | null | undefined) {
  if (!Array.isArray(values)) {
    return [];
  }

  return values.map((value) => normalizeText(value)).filter(Boolean);
}

function normalizeStringMap(values: Readonly<Record<string, string>>) {
  return Object.entries(values ?? {}).reduce<Record<string, string>>(
    (normalized, [key, value]) => {
      const normalizedKey = normalizeText(key).toLowerCase();
      const normalizedValue = normalizeText(value);

      if (normalizedKey && normalizedValue) {
        normalized[normalizedKey] = normalizedValue;
      }

      return normalized;
    },
    {},
  );
}

function mapToSearchText(values: Record<string, string>) {
  return Object.entries(values)
    .map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`)
    .join(" ");
}

function normalizeSpecKey(key: string) {
  return normalizeText(key).toLowerCase().replace(/[\s_-]+/g, "");
}

function normalizeKeyword(value: string) {
  return removeRiskyMarketingPhrases(value)
    .toLowerCase()
    .replace(/[^a-z0-9/+\s-]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function removeRiskyMarketingPhrases(text: string) {
  return normalizeText(text)
    .replace(/\b(?:best|perfect|ultimate|world'?s best|top[-\s]?rated)\b/gi, "")
    .replace(/\b(?:guaranteed|always|never|100%|unbreakable|indestructible)\b/gi, "")
    .replace(/\b(?:leak[-\s]?proof|spill[-\s]?proof|fail[-\s]?proof)\b/gi, "leak-resistant")
    .replace(/\s+/g, " ")
    .replace(/\s+,/g, ",")
    .trim();
}

function isComplianceSensitiveKeyword(keyword: string) {
  return /\b(?:fda|medical|clinically|therapeutic|cure|treat|prevent|certified|certification|non-toxic|bpa-free|phthalate-free|lead-free|child-safe|kid-safe|antibacterial|antimicrobial|sterile|hypoallergenic)\b/i.test(
    keyword,
  );
}

function isChildFacingProduct(product: NormalizedProduct) {
  return /\b(?:kid|kids|child|children|toddler|baby|infant|school)\b/i.test(
    product.allText,
  );
}

function isInsulatedProduct(product: NormalizedProduct) {
  return /\b(?:insulated|insulation|vacuum)\b/i.test(product.allText);
}

function hasMeasurement(text: string) {
  return /\b\d+(?:\.\d+)?\s?(?:fl\s?oz|oz|ml|l|liter|litre|g|kg|lb|in|cm|mm)\b/i.test(
    text,
  );
}

function containsAnyToken(text: string, tokens: string[]) {
  const normalizedText = text.toLowerCase();

  return tokens.some((token) => normalizedText.includes(token));
}

function tokenize(text: string) {
  return text
    .toLowerCase()
    .split(/[^a-z0-9/]+/i)
    .map((token) => token.trim())
    .filter((token) => token.length >= 3);
}

function uniqueStrings(values: string[]) {
  const seen = new Set<string>();

  return values.filter((value) => {
    if (seen.has(value)) {
      return false;
    }

    seen.add(value);
    return true;
  });
}

function countFlags(flags: ProductRiskFlag[], field: RiskField) {
  return flags.filter((item) => item.field === field).length;
}

function countComplianceFlags(flags: ProductRiskFlag[]) {
  return flags.filter(
    (item) =>
      item.type === "compliance" ||
      item.type === "category_risk" ||
      item.type === "exaggeration",
  ).length;
}

function impactFromGap(score: number, base: number, flagCount: number) {
  return clampScore(base + (100 - score) * 0.45 + flagCount * 8);
}

function blendScore(baseScore: number, readinessScore: number, baseWeight: number) {
  return clampScore(baseScore * baseWeight + readinessScore * (1 - baseWeight));
}

function severityPenalty(
  severity: ProductRiskFlag["severity"],
  multiplier: number,
) {
  const points: Record<ProductRiskFlag["severity"], number> = {
    low: 6,
    medium: 14,
    high: 28,
  };

  return points[severity] * multiplier;
}

function limitText(text: string, maxLength: number) {
  if (text.length <= maxLength) {
    return text;
  }

  return `${text.slice(0, maxLength - 1).trimEnd()}.`;
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
