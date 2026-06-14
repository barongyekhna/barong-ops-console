import { apiRequest } from "@/lib/api";

import type { SERPResult, SERPSearchRequest } from "./types";

const K16_SERP_SEARCH_PATH = "/k/serp/search";

export function runSERPSearch(payload: SERPSearchRequest): Promise<SERPResult> {
  return apiRequest<SERPResult>(K16_SERP_SEARCH_PATH, {
    body: payload,
    method: "POST",
  });
}
