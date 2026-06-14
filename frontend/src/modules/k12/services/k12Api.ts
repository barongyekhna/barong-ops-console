import {
  createReviewState,
  transitionState,
  type ReviewItemStatus,
  type ReviewStateSnapshot,
  type ReviewStatus,
  type VersionChangedField,
  type VersionJsonValue,
  type VersionRecord,
} from "./reviewState";

export type ProductPrimitiveValue = string | number | boolean;
export type ProductValueMap = Record<string, string>;

export type ProductAiCanonicalFields = {
  title: string;
  description: string;
  features: string[];
  keywords: string[];
  specs: ProductValueMap;
  dimensions: ProductValueMap;
  weight: string;
  minimum_age_years: number;
  dishwasher_safe: boolean;
};

export type ProductHumanEditFields = ProductAiCanonicalFields & {
  warnings: string[];
};

export const productReviewFields = [
  "title",
  "description",
  "features",
  "keywords",
  "specs",
  "dimensions",
  "weight",
  "minimum_age_years",
  "dishwasher_safe",
] as const;

export type ProductReviewField = (typeof productReviewFields)[number];

const versionedHumanEditFields = [...productReviewFields, "warnings"] as const;
type VersionedHumanEditField = (typeof versionedHumanEditFields)[number];

export const productReviewFieldLabels: Record<ProductReviewField, string> = {
  title: "Title",
  description: "Description",
  features: "Features",
  keywords: "Keywords",
  specs: "Specs",
  dimensions: "Dimensions",
  weight: "Weight",
  minimum_age_years: "Minimum Age Years",
  dishwasher_safe: "Dishwasher Safe",
};

export type RawProductInput = {
  original_input_text: string;
  original_language: string;
  original_json: Record<string, unknown>;
  serp_data?: Record<string, unknown>;
};

export type ReviewItem = {
  id: string;
  raw: string;
  canonical: string;
  status: ReviewItemStatus;
  ai_suggestion: string;
};

export type ProductReviewRecord = ReviewStateSnapshot & {
  review_id: string;
  source: "local_mock";
  raw_input: RawProductInput;
  ai_canonical: ProductAiCanonicalFields;
  human_edit: ProductHumanEditFields;
  review_item: ReviewItem;
};

const mockAiCanonical: ProductAiCanonicalFields = {
  title: "Stainless Steel Insulated Kids Water Bottle",
  description:
    "A compact double-wall insulated bottle for school lunches, day trips, and everyday hydration.",
  features: [
    "Double-wall vacuum insulation",
    "Leak-resistant straw lid",
    "Carry handle sized for children",
    "BPA-free contact surfaces",
  ],
  keywords: [
    "kids water bottle",
    "stainless steel",
    "straw lid",
    "12 oz",
  ],
  specs: {
    material: "18/8 stainless steel",
    capacity: "12 fl oz",
    lid_type: "Flip straw",
    recommended_age: "3+ years",
  },
  dimensions: {
    height: "7.8 in",
    diameter: "2.9 in",
  },
  weight: "9.6 oz",
  minimum_age_years: 3,
  dishwasher_safe: false,
};

const mockRawInputText =
  "Kids bottle, stainless, straw cap, 12oz, keeps drinks cold, school safe. Maybe age 3+.";

const mockReview: ProductReviewRecord = {
  review_id: "k12-review-local-001",
  source: "local_mock",
  ...createReviewState("draft", "k-series-product-knowledge-001"),
  raw_input: {
    original_input_text: mockRawInputText,
    original_language: "en",
    original_json: {
      marketplace_title: "Kids 12 oz Stainless Bottle with Straw Lid",
      bullet_points: [
        "Cold drinks stay chilled for school day",
        "Easy carry handle",
        "Leak resistant when closed",
      ],
      unit_payload: {
        capacity: {
          value: 12,
          unit: "fl oz",
        },
        item_weight: {
          value: 9.6,
          unit: "oz",
        },
      },
      safety_notes: ["Do not fill with boiling liquids"],
    },
    serp_data: {
      query: "kids stainless steel straw water bottle 12 oz",
      locale: "US",
      top_results: [
        {
          title: "12 oz Kids Insulated Bottle",
          source: "mock-serp",
          observed_capacity: "12 oz",
        },
        {
          title: "School Straw Bottle Stainless Steel",
          source: "mock-serp",
          observed_feature: "flip straw lid",
        },
      ],
    },
  },
  ai_canonical: mockAiCanonical,
  review_item: {
    id: "k12-review-item-local-001",
    raw: mockRawInputText,
    canonical: mockAiCanonical.description,
    status: "pending_review",
    ai_suggestion:
      "K13 hook placeholder: identify safety wording, age suitability, and unit normalization before final approval.",
  },
  human_edit: {
    ...mockAiCanonical,
    title: "Kids Stainless Steel Insulated Water Bottle, 12 oz",
    description:
      "A compact double-wall insulated bottle for school lunches, day trips, and everyday hydration.",
    features: [
      "Leak-resistant straw lid",
      "Double-wall vacuum insulation",
      "Carry handle sized for children",
      "Keeps drinks cold for school day",
    ],
    keywords: [
      "stainless steel",
      "kids water bottle",
      "straw lid",
      "school bottle",
    ],
    dimensions: {
      ...mockAiCanonical.dimensions,
      height: "7.9 in",
    },
    dishwasher_safe: true,
    warnings: ["Not for use with hot liquids"],
  },
};

function cloneReview(review: ProductReviewRecord): ProductReviewRecord {
  return JSON.parse(JSON.stringify(review)) as ProductReviewRecord;
}

function cloneHumanEditFields(
  fields: ProductHumanEditFields,
): ProductHumanEditFields {
  return JSON.parse(JSON.stringify(fields)) as ProductHumanEditFields;
}

function normalizeVersionValue(value: unknown): VersionJsonValue {
  if (value === null || value === undefined) {
    return null;
  }

  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => normalizeVersionValue(item));
  }

  if (typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    const normalized: Record<string, VersionJsonValue> = {};

    Object.keys(objectValue)
      .sort((leftKey, rightKey) => leftKey.localeCompare(rightKey))
      .forEach((key) => {
        normalized[key] = normalizeVersionValue(objectValue[key]);
      });

    return normalized;
  }

  return null;
}

function toVersionObject(value: unknown): Record<string, VersionJsonValue> {
  return normalizeVersionValue(value) as Record<string, VersionJsonValue>;
}

function stableVersionSerialize(value: unknown) {
  return JSON.stringify(normalizeVersionValue(value));
}

function getAiCanonicalValue(
  field: VersionedHumanEditField,
  aiCanonical: ProductAiCanonicalFields,
) {
  if (field === "warnings") {
    return null;
  }

  return normalizeVersionValue(aiCanonical[field as ProductReviewField]);
}

function getHumanEditValue(
  field: VersionedHumanEditField,
  humanEdit: ProductHumanEditFields,
) {
  return normalizeVersionValue(humanEdit[field]);
}

function isEmptyHumanOnlyValue(value: VersionJsonValue) {
  if (value === null) {
    return true;
  }

  if (typeof value === "string") {
    return value.trim().length === 0;
  }

  if (Array.isArray(value)) {
    return value.length === 0;
  }

  if (typeof value === "object") {
    return Object.keys(value).length === 0;
  }

  return false;
}

function buildHumanEditChangedFields(
  beforeHumanEdit: ProductHumanEditFields,
  afterHumanEdit: ProductHumanEditFields,
  aiCanonical: ProductAiCanonicalFields,
): VersionChangedField[] {
  return versionedHumanEditFields.flatMap((field) => {
    const beforeValue = getHumanEditValue(field, beforeHumanEdit);
    const afterValue = getHumanEditValue(field, afterHumanEdit);

    if (
      stableVersionSerialize(beforeValue) === stableVersionSerialize(afterValue)
    ) {
      return [];
    }

    return [
      {
        field,
        before_value: beforeValue,
        after_value: afterValue,
        ai_value: getAiCanonicalValue(field, aiCanonical),
        change_type: "human_edit",
      },
    ];
  });
}

function buildAiHumanDiffFields(
  aiCanonical: ProductAiCanonicalFields,
  humanEdit: ProductHumanEditFields,
): VersionChangedField[] {
  return versionedHumanEditFields.flatMap((field) => {
    const aiValue = getAiCanonicalValue(field, aiCanonical);
    const humanValue = getHumanEditValue(field, humanEdit);

    if (field === "warnings" && isEmptyHumanOnlyValue(humanValue)) {
      return [];
    }

    if (
      stableVersionSerialize(aiValue) === stableVersionSerialize(humanValue)
    ) {
      return [];
    }

    return [
      {
        field,
        before_value: aiValue,
        after_value: humanValue,
        ai_value: aiValue,
        change_type: "ai_vs_human",
      },
    ];
  });
}

function buildReviewStateChangedFields(
  beforeStatus: ReviewStatus,
  afterStatus: ReviewStatus,
): VersionChangedField[] {
  if (beforeStatus === afterStatus) {
    return [];
  }

  return [
    {
      field: "status",
      before_value: beforeStatus,
      after_value: afterStatus,
      change_type: "review_state",
    },
  ];
}

function buildVersionState(review: ProductReviewRecord) {
  const aiHumanDiffFields = buildAiHumanDiffFields(
    review.ai_canonical,
    review.human_edit,
  );

  return toVersionObject({
    ai_canonical: review.ai_canonical,
    ai_human_diff_fields: aiHumanDiffFields,
    human_edit: review.human_edit,
    status: review.status,
    updated_at: review.updated_at,
  });
}

function buildVersionStateSnapshot(
  review: ProductReviewRecord,
  aiHumanDiffFields: VersionChangedField[],
) {
  return toVersionObject({
    ai_human_diff_count: aiHumanDiffFields.length,
    ai_human_diff_fields: aiHumanDiffFields,
    product_id: review.product_id,
    review_id: review.review_id,
    state_log: review.state_log,
    status: review.status,
    updated_at: review.updated_at,
  });
}

function createVersionId() {
  const randomUUID = globalThis.crypto?.randomUUID;

  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto);
  }

  return `version-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function buildVersionRecord(
  beforeReview: ProductReviewRecord | null,
  afterReview: ProductReviewRecord,
  actionChangedFields: VersionChangedField[],
  user: string,
  timestamp: string,
): VersionRecord {
  const aiHumanDiffFields = buildAiHumanDiffFields(
    afterReview.ai_canonical,
    afterReview.human_edit,
  );

  return {
    version_id: createVersionId(),
    product_id: afterReview.product_id,
    before_state: beforeReview ? buildVersionState(beforeReview) : {},
    after_state: buildVersionState(afterReview),
    changed_fields: [...actionChangedFields, ...aiHumanDiffFields],
    state_snapshot: buildVersionStateSnapshot(afterReview, aiHumanDiffFields),
    user,
    timestamp,
  };
}

function appendVersionRecord(
  beforeReview: ProductReviewRecord,
  afterReview: ProductReviewRecord,
  actionChangedFields: VersionChangedField[],
  user: string,
  timestamp: string,
) {
  const versionRecord = buildVersionRecord(
    beforeReview,
    afterReview,
    actionChangedFields,
    user,
    timestamp,
  );

  return {
    ...afterReview,
    version_record: [...beforeReview.version_record, versionRecord],
  };
}

function withInitialVersionRecord(review: ProductReviewRecord) {
  const nextReview = cloneReview(review);
  const versionRecord = buildVersionRecord(
    null,
    nextReview,
    [],
    "operator",
    nextReview.updated_at,
  );

  return {
    ...nextReview,
    version_record: [versionRecord],
  };
}

function buildMockResponse(
  to: ReviewStatus,
  humanEdit: ProductHumanEditFields,
  user = "operator",
): ProductReviewRecord {
  const beforeReview = cloneReview(currentMockReview);
  const nextState = transitionState(beforeReview, to, user);
  const afterReview = {
    ...beforeReview,
    ...nextState,
    human_edit: cloneHumanEditFields(humanEdit),
  };
  const changedFields = [
    ...buildReviewStateChangedFields(beforeReview.status, afterReview.status),
    ...buildHumanEditChangedFields(
      beforeReview.human_edit,
      afterReview.human_edit,
      afterReview.ai_canonical,
    ),
  ];

  return appendVersionRecord(
    beforeReview,
    afterReview,
    changedFields,
    user,
    nextState.updated_at,
  );
}

function saveMockReview(
  humanEdit: ProductHumanEditFields,
  user = "operator",
): ProductReviewRecord {
  if (currentMockReview.status !== "draft") {
    throw new Error(
      `Draft edits are only allowed while status is draft. Current status: ${currentMockReview.status}`,
    );
  }

  const beforeReview = cloneReview(currentMockReview);
  const timestamp = new Date().toISOString();
  const afterReview = {
    ...beforeReview,
    human_edit: cloneHumanEditFields(humanEdit),
    updated_at: timestamp,
  };
  const changedFields = buildHumanEditChangedFields(
    beforeReview.human_edit,
    afterReview.human_edit,
    afterReview.ai_canonical,
  );

  return appendVersionRecord(
    beforeReview,
    afterReview,
    changedFields,
    user,
    timestamp,
  );
}

let currentMockReview = withInitialVersionRecord(mockReview);

export async function getProductReview(): Promise<ProductReviewRecord> {
  return cloneReview(currentMockReview);
}

export async function saveDraft(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = saveMockReview(humanEdit);

  return cloneReview(currentMockReview);
}

export async function markAiGenerated(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = buildMockResponse("ai_generated", humanEdit);

  return cloneReview(currentMockReview);
}

export async function requestReview(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = buildMockResponse("needs_review", humanEdit);

  return cloneReview(currentMockReview);
}

export async function markReviewed(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = buildMockResponse("reviewed", humanEdit);

  return cloneReview(currentMockReview);
}

export async function approve(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = buildMockResponse("approved", humanEdit);

  return cloneReview(currentMockReview);
}

export async function reject(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  currentMockReview = buildMockResponse("rejected", humanEdit);

  return cloneReview(currentMockReview);
}
