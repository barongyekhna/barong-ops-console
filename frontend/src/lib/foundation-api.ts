import { apiRequest } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";

export type FoundationListResponse = {
  items: Record<string, unknown>[];
  count: number;
  limit: number;
  offset: number;
};

export function foundationListRequest(path: string) {
  return apiRequest<FoundationListResponse>(path, {
    accessToken: readAccessToken(),
    method: "GET",
  });
}
