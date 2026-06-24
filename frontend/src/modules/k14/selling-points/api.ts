import { apiRequest } from "@/lib/api";

import type { ProductSellingPoints } from "./types";

const K14_SELLING_POINTS_PATH = "/k/selling-points";

export type GenerateSellingPointsPayload = Record<string, unknown>;

export function generateSellingPoints(
  product: GenerateSellingPointsPayload,
): Promise<ProductSellingPoints> {
  return apiRequest<ProductSellingPoints>(
    `${K14_SELLING_POINTS_PATH}/generate`,
    {
      body: {
        product,
        mode: "live",
      },
      method: "POST",
    },
  );
}

export function getSellingPoints(
  productId: string,
): Promise<ProductSellingPoints> {
  return apiRequest<ProductSellingPoints>(
    `${K14_SELLING_POINTS_PATH}/${encodeURIComponent(productId)}`,
    {
      method: "GET",
    },
  );
}
