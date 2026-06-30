"use client";

import { apiRequest } from "@/lib/api";

import type {
  RCommerceReviewResponse,
  RCommerceRunRequest,
  RCommerceRunResponse,
  RCommerceSkillResponse,
  RProductCandidate,
} from "./types";

export function runRCommerceTask(payload: RCommerceRunRequest) {
  return apiRequest<RCommerceRunResponse>("/r/commerce/run", {
    body: payload,
    method: "POST",
    timeoutMs: 30_000,
  });
}

export function reviewRCommerceProduct(
  action: "Save" | "Remove",
  product: RProductCandidate,
) {
  return apiRequest<RCommerceReviewResponse>("/r/commerce/review", {
    body: { action, product },
    method: "POST",
  });
}

export function getRCommerceSkills() {
  return apiRequest<RCommerceSkillResponse>("/r/commerce/skills", {
    method: "GET",
  });
}
