import { apiRequest } from "@/lib/api";

export type FoundationListResponse = {
  items: Record<string, unknown>[];
  count: number;
  limit: number;
  offset: number;
};

export function foundationListRequest(path: string) {
  return apiRequest<FoundationListResponse>(path, {
    method: "GET",
  });
}
