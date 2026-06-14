import { apiRequest } from "@/lib/api";

import type { ResearchRun } from "./types";

const K15_KEYWORD_RESEARCH_START_PATH = "/k/keyword-research/start";

export function startKeywordResearch(productId: string): Promise<ResearchRun> {
  return apiRequest<ResearchRun>(K15_KEYWORD_RESEARCH_START_PATH, {
    body: {
      product_id: productId,
    },
    method: "POST",
  });
}
