import { apiRequest } from "@/lib/api";

import type {
  CreateFeatureFlagPayload,
  FeatureFlagListResponse,
  FeatureFlagResponse,
  UpdateFeatureFlagPayload,
} from "./types";

const K23_FEATURE_FLAGS_PATH = "/k/feature-flags";

export function getFeatureFlags(): Promise<FeatureFlagListResponse> {
  return apiRequest<FeatureFlagListResponse>(K23_FEATURE_FLAGS_PATH);
}

export function createFeatureFlag(
  payload: CreateFeatureFlagPayload,
): Promise<FeatureFlagResponse> {
  return apiRequest<FeatureFlagResponse>(K23_FEATURE_FLAGS_PATH, {
    body: payload,
    method: "POST",
  });
}

export function updateFeatureFlag(
  flagId: string,
  payload: UpdateFeatureFlagPayload,
): Promise<FeatureFlagResponse> {
  return apiRequest<FeatureFlagResponse>(
    `${K23_FEATURE_FLAGS_PATH}/${encodeURIComponent(flagId)}`,
    {
      body: payload,
      method: "PATCH",
    },
  );
}
