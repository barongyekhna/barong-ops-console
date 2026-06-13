import type {
  ProductRiskAnalysis,
  ProductRiskFlag,
  ProductRiskInput,
  ProductRiskSuggestion,
  RiskField,
  RiskFlagType,
  RiskSeverity,
  RiskSuggestionReason,
} from "../types";

type NormalizedProduct = {
  title: string;
  description: string;
  features: string[];
  keywords: string[];
  specs: Record<string, string>;
  dimensions: Record<string, string>;
  weight: string;
  minimumAgeYears: number | null;
  fieldText: Record<RiskField, string>;
  allText: string;
};

type TextPattern = {
  expression: RegExp;
  type: RiskFlagType;
  severity: RiskSeverity;
  message: string;
};

type ScoreDetails = {
  complianceScore: number;
  seoScore: number;
  conversionScore: number;
};

const severityRiskPoints: Record<RiskSeverity, number> = {
  low: 6,
  medium: 14,
  high: 28,
};

const compliancePatterns: TextPattern[] = [
  {
    expression:
      /\b(?:fda[-\s]?(?:approved|cleared)|medical[-\s]?grade|clinically|therapeutic|cures?|treats?|prevents?)\b/i,
    type: "compliance",
    severity: "high",
    message:
      "Regulated health or approval claim requires reviewed source evidence before publishing.",
  },
  {
    expression:
      /\b(?:non[-\s]?toxic|bpa[-\s]?free|phthalate[-\s]?free|lead[-\s]?free|food[-\s]?grade|certified|certification|ce[-\s]?certified|ul[-\s]?listed)\b/i,
    type: "compliance",
    severity: "medium",
    message:
      "Compliance-sensitive material or certification claim should be verified against source evidence.",
  },
  {
    expression: /\b(?:child[-\s]?safe|kid[-\s]?safe|school[-\s]?safe|baby[-\s]?safe)\b/i,
    type: "compliance",
    severity: "high",
    message:
      "Safety claim for a child-facing product needs explicit reviewed evidence and warning context.",
  },
  {
    expression: /\b(?:antibacterial|antimicrobial|sterile|hypoallergenic)\b/i,
    type: "compliance",
    severity: "high",
    message:
      "Biological, sterility, or allergy-related claim is high-risk without reviewed substantiation.",
  },
];

const exaggerationPatterns: TextPattern[] = [
  {
    expression:
      /\b(?:best|perfect|ultimate|world'?s best|top[-\s]?rated|guaranteed|always|never|unbreakable|indestructible)\b/i,
    type: "exaggeration",
    severity: "medium",
    message:
      "Absolute or superiority wording can create unsupported marketing claims.",
  },
  {
    expression: /\b(?:100%|leak[-\s]?proof|spill[-\s]?proof|fail[-\s]?proof)\b/i,
    type: "exaggeration",
    severity: "medium",
    message:
      "Proof-style claim should be softened or backed by reviewed test evidence.",
  },
];

const uncertaintyPatterns: TextPattern[] = [
  {
    expression: /\b(?:unknown|tbd|to be confirmed|maybe|possibly|approx\.?|approximately|around)\b/i,
    type: "missing_info",
    severity: "low",
    message:
      "Uncertain wording indicates the product fact should be reviewed or replaced with a verified value.",
  },
];

export function analyzeProductRisk(
  product: ProductRiskInput,
): ProductRiskAnalysis {
  const normalized = normalizeProduct(product);
  const flags = uniqueFlags([
    ...detectMissingInformation(normalized),
    ...detectTextRisks(normalized),
    ...detectCategoryRisks(normalized),
  ]);
  const scoreDetails = calculateScoreDetails(normalized, flags);
  const suggestions = uniqueSuggestions(
    buildSuggestions(normalized, flags, scoreDetails),
  );

  return {
    risk_score: calculateRiskScore(flags, scoreDetails),
    compliance_score: scoreDetails.complianceScore,
    seo_score: scoreDetails.seoScore,
    conversion_score: scoreDetails.conversionScore,
    flags,
    suggestions,
  };
}

export default analyzeProductRisk;

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
  const specsText = [
    mapToSearchText(specs),
    mapToSearchText(dimensions),
    weight ? `weight ${weight}` : "",
    minimumAgeYears !== null ? `minimum age ${minimumAgeYears}` : "",
    product.dishwasher_safe ? "dishwasher safe" : "not dishwasher safe",
  ].join(" ");

  const fieldText: Record<RiskField, string> = {
    title,
    description: [description, ...features, ...keywords].join(" "),
    specs: specsText,
  };

  return {
    title,
    description,
    features,
    keywords,
    specs,
    dimensions,
    weight,
    minimumAgeYears,
    fieldText,
    allText: Object.values(fieldText).join(" ").toLowerCase(),
  };
}

function detectMissingInformation(
  product: NormalizedProduct,
): ProductRiskFlag[] {
  const flags: ProductRiskFlag[] = [];

  if (!product.title) {
    flags.push(flag("missing_info", "high", "title", "Product title is missing."));
  } else if (product.title.length < 28) {
    flags.push(
      flag(
        "missing_info",
        "low",
        "title",
        "Product title may be too short to carry product type and key attributes.",
      ),
    );
  }

  if (!product.description) {
    flags.push(
      flag("missing_info", "high", "description", "Product description is missing."),
    );
  } else if (product.description.length < 70) {
    flags.push(
      flag(
        "missing_info",
        "low",
        "description",
        "Description is short and may not provide enough review context.",
      ),
    );
  }

  if (Object.keys(product.specs).length === 0) {
    flags.push(
      flag("missing_info", "high", "specs", "Specs are missing from the canonical product."),
    );
  }

  if (!hasSpecValue(product, ["material", "materials", "composition"])) {
    flags.push(
      flag(
        "missing_info",
        "medium",
        "specs",
        "Material or composition is missing from reviewed specs.",
      ),
    );
  }

  if (
    isLikelyCapacityProduct(product) &&
    !hasSpecValue(product, ["capacity", "volume", "size"])
  ) {
    flags.push(
      flag(
        "missing_info",
        "medium",
        "specs",
        "Capacity or volume is missing for a capacity-driven product.",
      ),
    );
  }

  if (Object.keys(product.dimensions).length === 0) {
    flags.push(
      flag(
        "missing_info",
        "medium",
        "specs",
        "Product dimensions are missing; downstream commerce and media gates may need them.",
      ),
    );
  }

  if (!product.weight) {
    flags.push(
      flag(
        "missing_info",
        "medium",
        "specs",
        "Product weight is missing; do not infer weight for shipping or product facts.",
      ),
    );
  }

  return flags;
}

function detectTextRisks(product: NormalizedProduct): ProductRiskFlag[] {
  const flags: ProductRiskFlag[] = [];

  for (const field of riskFields()) {
    const text = product.fieldText[field];

    for (const pattern of [
      ...compliancePatterns,
      ...exaggerationPatterns,
      ...uncertaintyPatterns,
    ]) {
      if (pattern.expression.test(text)) {
        flags.push(
          flag(pattern.type, pattern.severity, field, pattern.message),
        );
      }
    }
  }

  return flags;
}

function detectCategoryRisks(product: NormalizedProduct): ProductRiskFlag[] {
  const flags: ProductRiskFlag[] = [];

  if (isChildFacingProduct(product)) {
    if (!hasReviewedAgeGuidance(product)) {
      flags.push(
        flag(
          "compliance",
          "high",
          "specs",
          "Child-facing product is missing reviewed age guidance.",
        ),
      );
    }

    if (!hasSafetyContext(product)) {
      flags.push(
        flag(
          "category_risk",
          "medium",
          "description",
          "Child-facing product should expose reviewed safety notes before downstream use.",
        ),
      );
    }
  }

  if (isFoodContactProduct(product) && !hasSpecValue(product, ["material"])) {
    flags.push(
      flag(
        "compliance",
        "high",
        "specs",
        "Food-contact product needs a reviewed material fact before claim or commerce use.",
      ),
    );
  }

  if (isElectricalProduct(product) && !hasElectricalSafetySpec(product)) {
    flags.push(
      flag(
        "category_risk",
        "medium",
        "specs",
        "Electrical or battery product is missing reviewed electrical/safety specs.",
      ),
    );
  }

  if (isHealthSensitiveProduct(product)) {
    flags.push(
      flag(
        "category_risk",
        "high",
        "description",
        "Health, ingestible, cosmetic, or medical category terms require stricter compliance review.",
      ),
    );
  }

  return flags;
}

function calculateScoreDetails(
  product: NormalizedProduct,
  flags: ProductRiskFlag[],
): ScoreDetails {
  return {
    complianceScore: calculateComplianceScore(flags),
    seoScore: calculateSeoScore(product, flags),
    conversionScore: calculateConversionScore(product, flags),
  };
}

function calculateComplianceScore(flags: ProductRiskFlag[]) {
  const penalty = flags.reduce((total, item) => {
    if (item.type === "compliance") {
      return total + severityPenalty(item.severity, 1.15);
    }

    if (item.type === "category_risk") {
      return total + severityPenalty(item.severity, 0.95);
    }

    if (item.type === "exaggeration") {
      return total + severityPenalty(item.severity, 0.7);
    }

    if (item.field === "specs") {
      return total + severityPenalty(item.severity, 0.45);
    }

    return total;
  }, 0);

  return clampScore(100 - penalty);
}

function calculateSeoScore(
  product: NormalizedProduct,
  flags: ProductRiskFlag[],
) {
  let penalty = 0;

  if (!product.title) {
    penalty += 42;
  } else {
    if (product.title.length < 35) {
      penalty += 12;
    }

    if (product.title.length > 90) {
      penalty += 18;
    } else if (product.title.length > 72) {
      penalty += 6;
    }

    if (!titleIncludesAnyKeyword(product)) {
      penalty += 8;
    }
  }

  if (!product.description) {
    penalty += 24;
  } else if (product.description.length < 90) {
    penalty += 10;
  } else if (product.description.length > 500) {
    penalty += 8;
  }

  if (product.keywords.length < 3) {
    penalty += 12;
  } else if (product.keywords.length > 8) {
    penalty += 5;
  }

  if (
    hasSpecValue(product, ["capacity", "volume", "size"]) &&
    !hasMeasurement(product.title)
  ) {
    penalty += 6;
  }

  if (
    hasSpecValue(product, ["material", "materials"]) &&
    !containsAnyToken(product.title, getSpecTokens(product, ["material", "materials"]))
  ) {
    penalty += 5;
  }

  penalty += flags.filter(
    (item) => item.field === "title" && item.type === "exaggeration",
  ).length * 8;

  return clampScore(100 - penalty);
}

function calculateConversionScore(
  product: NormalizedProduct,
  flags: ProductRiskFlag[],
) {
  let penalty = 0;

  if (!product.description) {
    penalty += 25;
  } else if (product.description.length < 90) {
    penalty += 12;
  }

  if (product.features.length === 0) {
    penalty += 18;
  } else if (product.features.length < 3) {
    penalty += 8;
  }

  if (!hasSpecValue(product, ["material", "materials"])) {
    penalty += 12;
  }

  if (
    isLikelyCapacityProduct(product) &&
    !hasSpecValue(product, ["capacity", "volume", "size"])
  ) {
    penalty += 12;
  }

  if (Object.keys(product.dimensions).length === 0) {
    penalty += 10;
  }

  if (!product.weight) {
    penalty += 10;
  }

  if (isChildFacingProduct(product) && !hasSafetyContext(product)) {
    penalty += 8;
  }

  penalty += flags.filter((item) => item.type === "exaggeration").length * 5;

  return clampScore(100 - penalty);
}

function calculateRiskScore(
  flags: ProductRiskFlag[],
  scoreDetails: ScoreDetails,
) {
  const flagPoints = flags.reduce(
    (total, item) => total + severityRiskPoints[item.severity],
    0,
  );
  const scoreGapPoints =
    (100 - scoreDetails.complianceScore) * 0.3 +
    (100 - scoreDetails.seoScore) * 0.12 +
    (100 - scoreDetails.conversionScore) * 0.12;

  return clampScore(flagPoints + scoreGapPoints);
}

function buildSuggestions(
  product: NormalizedProduct,
  flags: ProductRiskFlag[],
  scoreDetails: ScoreDetails,
): ProductRiskSuggestion[] {
  const suggestions: ProductRiskSuggestion[] = [];

  if (
    scoreDetails.seoScore < 92 ||
    hasFieldFlag(flags, "title") ||
    shouldSuggestTitle(product)
  ) {
    suggestions.push(
      suggestion("title", buildTitleSuggestion(product), "SEO"),
    );
  }

  if (
    scoreDetails.conversionScore < 92 ||
    hasFieldFlag(flags, "description") ||
    shouldSuggestDescription(product)
  ) {
    suggestions.push(
      suggestion("description", buildDescriptionSuggestion(product), "clarity"),
    );
  }

  if (hasFieldFlag(flags, "specs") || scoreDetails.complianceScore < 92) {
    suggestions.push(
      suggestion("specs", buildSpecsSuggestion(product, flags), "compliance"),
    );
  }

  return suggestions;
}

function buildTitleSuggestion(product: NormalizedProduct) {
  const baseTitle = removeRiskyMarketingPhrases(product.title) || inferTitle(product);
  const additions: string[] = [];
  const material = getSpecValue(product, ["material", "materials"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);

  if (capacity && !hasMeasurement(baseTitle)) {
    additions.push(capacity);
  }

  if (material && !containsAnyToken(baseTitle, tokenize(material))) {
    additions.push(material);
  }

  return limitText(
    [baseTitle, ...additions].filter(Boolean).join(", "),
    92,
  );
}

function buildDescriptionSuggestion(product: NormalizedProduct) {
  const cleanedDescription = removeRiskyMarketingPhrases(product.description);
  const material = getSpecValue(product, ["material", "materials"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const lidType = getSpecValue(product, ["lid_type", "lid type", "lid"]);
  const ageText =
    product.minimumAgeYears !== null && product.minimumAgeYears > 0
      ? `recommended for ages ${product.minimumAgeYears}+`
      : "";
  const factFragments = [
    material,
    capacity ? `${capacity} capacity` : "",
    lidType ? `${lidType} lid` : "",
    ageText,
  ].filter(Boolean);
  const factualSentence =
    factFragments.length > 0
      ? `Key reviewed facts: ${factFragments.join(", ")}.`
      : "Add reviewed facts for material, size, use case, and safety context.";
  const safetySentence =
    isChildFacingProduct(product) && !hasSafetyContext(product)
      ? "Include reviewed safety notes before publish."
      : "";

  return [cleanedDescription || inferDescription(product), factualSentence, safetySentence]
    .filter(Boolean)
    .join(" ");
}

function buildSpecsSuggestion(
  product: NormalizedProduct,
  flags: ProductRiskFlag[],
) {
  const missingItems = [
    !hasSpecValue(product, ["material", "materials"]) ? "material" : "",
    isLikelyCapacityProduct(product) &&
    !hasSpecValue(product, ["capacity", "volume", "size"])
      ? "capacity"
      : "",
    Object.keys(product.dimensions).length === 0 ? "dimensions" : "",
    !product.weight ? "weight" : "",
    isChildFacingProduct(product) && !hasReviewedAgeGuidance(product)
      ? "age guidance"
      : "",
  ].filter(Boolean);

  const hasClaimRisk = flags.some(
    (item) => item.type === "compliance" || item.type === "exaggeration",
  );

  if (missingItems.length > 0 && hasClaimRisk) {
    return `Add reviewed ${missingItems.join(
      ", ",
    )} specs and verify or remove compliance-sensitive claims before downstream use.`;
  }

  if (missingItems.length > 0) {
    return `Add reviewed ${missingItems.join(
      ", ",
    )} specs before downstream commerce, SEO, or content use.`;
  }

  if (hasClaimRisk) {
    return "Attach reviewed source evidence for compliance-sensitive claims or remove those claims from canonical copy.";
  }

  return "Keep specs factual and reviewed; do not infer certifications, dimensions, weight, or category facts from product type alone.";
}

function flag(
  type: RiskFlagType,
  severity: RiskSeverity,
  field: RiskField,
  message: string,
): ProductRiskFlag {
  return {
    type,
    severity,
    field,
    message,
  };
}

function suggestion(
  field: RiskField,
  suggestionText: string,
  reason: RiskSuggestionReason,
): ProductRiskSuggestion {
  return {
    field,
    suggestion: suggestionText,
    reason,
  };
}

function uniqueFlags(flags: ProductRiskFlag[]) {
  const seen = new Set<string>();

  return flags.filter((item) => {
    const key = `${item.type}:${item.severity}:${item.field}:${item.message}`;

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function uniqueSuggestions(suggestions: ProductRiskSuggestion[]) {
  const seen = new Set<RiskField>();

  return suggestions.filter((item) => {
    if (seen.has(item.field)) {
      return false;
    }

    seen.add(item.field);
    return true;
  });
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

function riskFields(): RiskField[] {
  return ["title", "description", "specs"];
}

function hasFieldFlag(flags: ProductRiskFlag[], field: RiskField) {
  return flags.some((item) => item.field === field);
}

function hasSpecValue(product: NormalizedProduct, keys: string[]) {
  return getSpecValue(product, keys).length > 0;
}

function getSpecValue(product: NormalizedProduct, keys: string[]) {
  const normalizedKeys = keys.map((key) => normalizeSpecKey(key));
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

function normalizeSpecKey(key: string) {
  return normalizeText(key).toLowerCase().replace(/[\s_-]+/g, "");
}

function hasReviewedAgeGuidance(product: NormalizedProduct) {
  return (
    product.minimumAgeYears !== null &&
    product.minimumAgeYears > 0 &&
    (hasSpecValue(product, ["recommended_age", "minimum_age", "age"]) ||
      /\b(?:ages?|years?|months?|\d+\+)\b/i.test(product.fieldText.specs))
  );
}

function hasSafetyContext(product: NormalizedProduct) {
  return /\b(?:warning|not for|avoid|supervision|choking|hot liquids?|boiling|safety note)\b/i.test(
    product.allText,
  );
}

function hasElectricalSafetySpec(product: NormalizedProduct) {
  return hasSpecValue(product, [
    "voltage",
    "wattage",
    "battery",
    "certification",
    "certifications",
    "safety",
  ]);
}

function isChildFacingProduct(product: NormalizedProduct) {
  return /\b(?:kid|kids|child|children|toddler|baby|infant|school)\b/i.test(
    product.allText,
  );
}

function isFoodContactProduct(product: NormalizedProduct) {
  return /\b(?:bottle|cup|mug|tumbler|lunch|food|drink|straw|plate|bowl|utensil)\b/i.test(
    product.allText,
  );
}

function isLikelyCapacityProduct(product: NormalizedProduct) {
  return /\b(?:bottle|cup|mug|tumbler|jar|container|bag|box|pitcher|kettle|pot)\b/i.test(
    product.allText,
  );
}

function isElectricalProduct(product: NormalizedProduct) {
  return /\b(?:battery|batteries|electric|electrical|charger|usb|led|lamp|voltage|watt|powered)\b/i.test(
    product.allText,
  );
}

function isHealthSensitiveProduct(product: NormalizedProduct) {
  return /\b(?:medical|medicine|supplement|vitamin|cosmetic|skin|skincare|therapeutic|clinical|treat|cure|prevent)\b/i.test(
    product.allText,
  );
}

function hasMeasurement(text: string) {
  return /\b\d+(?:\.\d+)?\s?(?:fl\s?oz|oz|ml|l|liter|litre|g|kg|lb|in|cm|mm)\b/i.test(
    text,
  );
}

function titleIncludesAnyKeyword(product: NormalizedProduct) {
  if (product.keywords.length === 0 || !product.title) {
    return true;
  }

  const title = product.title.toLowerCase();

  return product.keywords.some((keyword) =>
    tokenize(keyword).some((token) => title.includes(token)),
  );
}

function shouldSuggestTitle(product: NormalizedProduct) {
  return (
    !product.title ||
    product.title.length < 35 ||
    product.title.length > 90 ||
    (hasSpecValue(product, ["capacity", "volume", "size"]) &&
      !hasMeasurement(product.title))
  );
}

function shouldSuggestDescription(product: NormalizedProduct) {
  return (
    !product.description ||
    product.description.length < 90 ||
    (isChildFacingProduct(product) && !hasSafetyContext(product))
  );
}

function inferTitle(product: NormalizedProduct) {
  const material = getSpecValue(product, ["material", "materials"]);
  const capacity = getSpecValue(product, ["capacity", "volume", "size"]);
  const productType = inferProductType(product);

  return [material, isChildFacingProduct(product) ? "Kids" : "", productType, capacity]
    .filter(Boolean)
    .join(" ");
}

function inferDescription(product: NormalizedProduct) {
  const title = product.title || inferTitle(product) || "Product";

  return `${title} with reviewed product facts for content, SEO, and compliance review.`;
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
  ];
  const matched = typePatterns.find(([expression]) =>
    expression.test(product.allText),
  );

  return matched?.[1] ?? "Product";
}

function removeRiskyMarketingPhrases(text: string) {
  return text
    .replace(/\b(?:best|perfect|ultimate|world'?s best|top[-\s]?rated)\b/gi, "")
    .replace(/\b(?:guaranteed|always|never|100%|unbreakable|indestructible)\b/gi, "")
    .replace(/\b(?:leak[-\s]?proof|spill[-\s]?proof|fail[-\s]?proof)\b/gi, "leak-resistant")
    .replace(/\s+/g, " ")
    .replace(/\s+,/g, ",")
    .trim();
}

function containsAnyToken(text: string, tokens: string[]) {
  const normalizedText = text.toLowerCase();

  return tokens.some((token) => normalizedText.includes(token));
}

function getSpecTokens(product: NormalizedProduct, keys: string[]) {
  return tokenize(getSpecValue(product, keys));
}

function tokenize(text: string) {
  return text
    .toLowerCase()
    .split(/[^a-z0-9/]+/i)
    .map((token) => token.trim())
    .filter((token) => token.length >= 3);
}

function limitText(text: string, maxLength: number) {
  if (text.length <= maxLength) {
    return text;
  }

  return `${text.slice(0, maxLength - 1).trimEnd()}.`;
}

function severityPenalty(severity: RiskSeverity, multiplier: number) {
  return severityRiskPoints[severity] * multiplier;
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}
