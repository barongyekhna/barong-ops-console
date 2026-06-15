export type FeatureFlagScope = "global" | "module" | "product" | "user";

export type FeatureFlagModule =
  | "K13"
  | "K14"
  | "K15"
  | "K16"
  | "K17"
  | "K18"
  | "K19"
  | "K20"
  | "K23";

export type FeatureFlag = {
  id: string;
  key: string;
  enabled: boolean;
  scope: FeatureFlagScope;
  module: FeatureFlagModule;
  description: string;
  fallback_value: boolean;
  created_at: string;
  updated_at: string;
};

export type CreateFeatureFlagPayload = {
  key: string;
  enabled: boolean;
  scope: FeatureFlagScope;
  module: FeatureFlagModule;
  description?: string;
  fallback_value: boolean;
};

export type UpdateFeatureFlagPayload = {
  enabled?: boolean;
  scope?: FeatureFlagScope;
  description?: string;
  fallback_value?: boolean;
};

export type FeatureFlagResponse = {
  feature_flag: FeatureFlag;
  status: "created" | "updated";
  timestamp: string;
};

export type FeatureFlagListResponse = {
  feature_flags: FeatureFlag[];
  status: "ok";
  timestamp: string;
};

export type FeatureFlagFilterValue<T extends string> = T | "all";

export const K23_F_MODE = "admin_ui_only";
export const K23_RUNTIME = "no_execution";
export const K23_CONTROLLED_ACCESS = true;

export const featureFlagScopes: FeatureFlagScope[] = [
  "global",
  "module",
  "product",
  "user",
];

export const featureFlagModules: FeatureFlagModule[] = [
  "K13",
  "K14",
  "K15",
  "K16",
  "K17",
  "K18",
  "K19",
  "K20",
  "K23",
];

export const moduleLabels: Record<FeatureFlagModule, string> = {
  K13: "K13 AI analysis",
  K14: "K14 selling points",
  K15: "K15 research",
  K16: "K16 SERP",
  K17: "K17 ChatGPT filter",
  K18: "K18 Claude filter",
  K19: "K19 keywords",
  K20: "K20 risk governance",
  K23: "K23 control plane",
};
