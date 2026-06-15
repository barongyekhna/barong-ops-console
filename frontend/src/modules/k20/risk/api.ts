import { apiRequest } from "@/lib/api";

import type {
  CreateRiskPayload,
  RiskListResponse,
  RiskTermResponse,
  UpdateRiskPayload,
} from "./types";

const K20_RISKS_PATH = "/k/risks";

export function getRisks(): Promise<RiskListResponse> {
  return apiRequest<RiskListResponse>(K20_RISKS_PATH);
}

export function createRisk(
  payload: CreateRiskPayload,
): Promise<RiskTermResponse> {
  return apiRequest<RiskTermResponse>(K20_RISKS_PATH, {
    body: payload,
    method: "POST",
  });
}

export function updateRisk(
  riskId: string,
  payload: UpdateRiskPayload,
): Promise<RiskTermResponse> {
  return apiRequest<RiskTermResponse>(
    `${K20_RISKS_PATH}/${encodeURIComponent(riskId)}`,
    {
      body: payload,
      method: "PATCH",
    },
  );
}

export function deleteRisk(riskId: string): Promise<RiskTermResponse> {
  return apiRequest<RiskTermResponse>(
    `${K20_RISKS_PATH}/${encodeURIComponent(riskId)}`,
    {
      method: "DELETE",
    },
  );
}
