"use client";

import type {
  RwProductsResponse,
  RwRulesResponse,
  RwStatus,
} from "@/modules/r/warehouse/types";

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error("R-W mock data request failed.");
  }

  return (await response.json()) as T;
}

export function getRwStatus() {
  return readJson<RwStatus>("/api/rw/status");
}

export function getRwProducts() {
  return readJson<RwProductsResponse>("/api/rw/products");
}

export function getRwRules() {
  return readJson<RwRulesResponse>("/api/rw/rules");
}

