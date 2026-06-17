import { apiRequest } from "@/lib/api";

export type CapabilityRecordListResponse = {
  items: Record<string, unknown>[];
  count: number;
  limit: number;
  offset: number;
};

export function capabilityRecordListRequest(path: string) {
  return apiRequest<CapabilityRecordListResponse>(path, {
    method: "GET",
  });
}
