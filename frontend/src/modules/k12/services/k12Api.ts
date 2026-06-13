import { createReviewState, type ReviewStatus } from "./reviewState";

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

export type ProductReviewRecord = {
  review_id: string;
  product_id: string;
  source: "local_mock";
  status: ReviewStatus;
  raw_input: RawProductInput;
  ai_canonical: ProductAiCanonicalFields;
  human_edit: ProductHumanEditFields;
  updated_at: string;
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

const mockReview: ProductReviewRecord = {
  review_id: "k12-review-local-001",
  product_id: "k-series-product-knowledge-001",
  source: "local_mock",
  ...createReviewState("needs_review"),
  raw_input: {
    original_input_text:
      "Kids bottle, stainless, straw cap, 12oz, keeps drinks cold, school safe. Maybe age 3+.",
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

function buildMockResponse(
  status: ReviewStatus,
  humanEdit: ProductHumanEditFields,
): ProductReviewRecord {
  return {
    ...cloneReview(mockReview),
    status,
    human_edit: cloneHumanEditFields(humanEdit),
    updated_at: new Date().toISOString(),
  };
}

export async function getProductReview(): Promise<ProductReviewRecord> {
  return cloneReview(mockReview);
}

export async function saveDraft(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  return buildMockResponse("draft", humanEdit);
}

export async function markReviewed(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  return buildMockResponse("reviewed", humanEdit);
}

export async function approve(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  return buildMockResponse("approved", humanEdit);
}

export async function reject(
  humanEdit: ProductHumanEditFields,
): Promise<ProductReviewRecord> {
  return buildMockResponse("rejected", humanEdit);
}
