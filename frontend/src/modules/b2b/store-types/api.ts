"use client";

// B2B 店型的接口层。请求统一走 `lib/api.ts`（超时/重试/401 派发/中文兜底）。

import { b2bRequest } from "../api-base";

const LABEL = "B2B 店型";

const BASE = "/b2b/store-types";

export type OutreachStatus = "idle" | "active" | "paused" | "retired";

export type StoreTypeCategory = {
  id: string;
  category_prefix: string[];
};

export type StoreType = {
  id: string;
  key: string;
  label: string;
  outreach_status: OutreachStatus;
  sort_order: number;
  notes: string | null;
  categories: StoreTypeCategory[];
  total_items: number;
  ready_items: number;
  prospecting_unlocked: boolean;
  shortfall: number;
  prospects_new: number;
  prospects_approved: number;
  newly_added: boolean;
};

export type StoreTypeList = {
  store_types: StoreType[];
  min_ready_items: number;
  max_active: number;
  active_keys: string[];
};

export async function getStoreTypes(): Promise<StoreTypeList> {
  return b2bRequest<StoreTypeList>(BASE, LABEL);
}

export async function createStoreType(payload: {
  key: string;
  label: string;
}): Promise<StoreType> {
  return b2bRequest<StoreType>(BASE, LABEL, { body: payload, method: "POST" });
}

export async function patchStoreType(
  key: string,
  payload: { label?: string; notes?: string; outreach_status?: OutreachStatus },
): Promise<StoreType> {
  return b2bRequest<StoreType>(`${BASE}/${encodeURIComponent(key)}`, LABEL, {
    body: payload,
    method: "PATCH",
  });
}

export async function addStoreTypeCategory(
  key: string,
  categoryPrefix: string[],
): Promise<StoreType> {
  return b2bRequest<StoreType>(
    `${BASE}/${encodeURIComponent(key)}/categories`,
    LABEL,
    { body: { category_prefix: categoryPrefix }, method: "POST" },
  );
}

export async function removeStoreTypeCategory(
  key: string,
  categoryId: string,
): Promise<StoreType> {
  return b2bRequest<StoreType>(
    `${BASE}/${encodeURIComponent(key)}` +
      `/categories/${encodeURIComponent(categoryId)}`,
    LABEL,
    { method: "DELETE" },
  );
}
