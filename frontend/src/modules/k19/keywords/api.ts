import { apiRequest } from "@/lib/api";

import type {
  CreateKeywordPayload,
  KeywordEntryResponse,
  KeywordListResponse,
  UpdateKeywordPayload,
} from "./types";

const K19_KEYWORDS_PATH = "/k/keywords";

export function createKeyword(
  payload: CreateKeywordPayload,
): Promise<KeywordEntryResponse> {
  return apiRequest<KeywordEntryResponse>(K19_KEYWORDS_PATH, {
    body: payload,
    method: "POST",
  });
}

export function getKeywordsByProduct(
  productId: string,
): Promise<KeywordListResponse> {
  return apiRequest<KeywordListResponse>(
    `${K19_KEYWORDS_PATH}/${encodeURIComponent(productId)}`,
  );
}

export function updateKeyword(
  keywordId: string,
  payload: UpdateKeywordPayload,
): Promise<KeywordEntryResponse> {
  return apiRequest<KeywordEntryResponse>(
    `${K19_KEYWORDS_PATH}/${encodeURIComponent(keywordId)}`,
    {
      body: payload,
      method: "PATCH",
    },
  );
}

export function deleteKeyword(keywordId: string): Promise<KeywordEntryResponse> {
  return apiRequest<KeywordEntryResponse>(
    `${K19_KEYWORDS_PATH}/${encodeURIComponent(keywordId)}`,
    {
      method: "DELETE",
    },
  );
}
