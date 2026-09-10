/**
 * M 系列 · 出货成本明细的接口层。
 *
 * 路径都在 `/mfg/cost` 下(见后端 cost/router.py 的说明),错误翻译沿用库存那套:
 * FastAPI 422 取第一条 msg,其余原样抛。
 */

import { ApiError, apiRequest } from "@/lib/api";

const LABEL = "出货成本";

export type Basis = "actual" | "estimate";
export type LaborMode = "per_unit" | "per_batch";
export type ShareMode = "full" | "price_only";

export type BatchDraw = {
  movement_id: string;
  qty: string;
  unit_price: string | null;
  unit_freight: string | null;
  at: string;
  estimated: boolean;
  extrapolated: boolean;
};

export type CostLine = {
  kind: "material" | "labor";
  code: string | null;
  name: string;
  unit: string;
  mode: string | null;
  bom_qty: string | null;
  qty: string;
  unit_price: string | null;
  unit_freight: string | null;
  line_material: string | null;
  line_freight: string | null;
  line_total: string | null;
  missing_price: boolean;
  price_source: string | null;
  crosses_batches: boolean;
  extrapolated: string | null;
  estimated_price: boolean;
  batches: BatchDraw[];
};

export type CostTotals = {
  material_total: string | null;
  freight_total: string | null;
  labor_total: string | null;
  unit_cost: string | null;
  missing_price_count: number;
};

export type CostSheetPreview = {
  product_id: string;
  product_code: string;
  product_name: string;
  product_unit: string;
  batch_qty: string;
  basis: Basis;
  source_document_id: string | null;
  source_doc_no: string | null;
  stock: string;
  materials: CostLine[];
  labor: CostLine[];
  totals: CostTotals;
  sale_price: string | null;
  unit_margin: string | null;
  margin_rate: string | null;
  batch_total: string | null;
  has_volatile: boolean;
  expires_on: string;
  valid_days: number;
};

export type ProductCostRow = {
  product_id: string;
  code: string;
  name: string;
  unit: string;
  stock: string;
  basis: Basis;
  unit_cost: string | null;
  sale_price: string | null;
  margin_rate: string | null;
  missing_price_count: number;
  bom_line_count: number;
  labor_line_count: number;
};

export type LaborProcess = {
  id: string;
  name: string;
  note: string | null;
  position: number;
  is_archived: boolean;
  rate: string | null;
  rate_effective_date: string | null;
  used_by_product_count: number;
};

export type LaborLine = {
  id: string;
  process_id: string;
  process_name: string;
  mode: LaborMode;
  qty: string;
  rate: string | null;
  position: number;
};

export type SalePrice = {
  id: string;
  unit_price: string;
  effective_date: string;
  note: string | null;
  created_by_name: string;
  created_at: string;
};

export type LaborRate = {
  id: string;
  rate: string;
  effective_date: string;
  note: string | null;
  created_by_name: string;
  created_at: string;
};

export type CostSheet = {
  id: string;
  sheet_no: string;
  product_id: string;
  product_code: string;
  product_name: string;
  product_unit: string;
  batch_qty: string;
  basis: Basis;
  expires_on: string;
  has_volatile: boolean;
  missing_price_count: number;
  material_total: string | null;
  freight_total: string | null;
  labor_total: string | null;
  unit_cost: string | null;
  sale_price: string | null;
  actor_name: string;
  note: string | null;
  created_at: string;
};

export type CostShare = {
  id: string;
  share_mode: ShareMode;
  recipient_user_id: string;
  recipient_name: string;
  conversation_id: string;
  message_id: string;
  verified_at: string | null;
  actor_name: string;
  created_at: string;
};

export type CostSheetDetail = CostSheet & {
  materials: CostLine[];
  labor: CostLine[];
  shares: CostShare[];
};

export type ShareResult = {
  sheet_no: string;
  share_mode: ShareMode;
  delivered: CostShare[];
  failed: { recipient_user_id: number; error: string }[];
};

function rethrow(error: unknown): never {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  const detail = error.detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string } | undefined;
    throw new Error(first?.msg || `${LABEL}（${error.status}）`);
  }
  if (typeof detail === "string" && detail) {
    throw new Error(detail);
  }
  throw error;
}

function get<T>(path: string, params?: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") {
      query.set(key, value);
    }
  }
  const qs = query.toString();
  return apiRequest<T>(`/mfg/cost${path}${qs ? `?${qs}` : ""}`).catch(rethrow);
}

function send<T>(method: "POST" | "PATCH" | "PUT", path: string, body: unknown) {
  return apiRequest<T>(`/mfg/cost${path}`, { body, method }).catch(rethrow);
}

export const listProductCosts = (includeArchived = false) =>
  get<{ items: ProductCostRow[]; total: number }>("/products", {
    include_archived: includeArchived ? "true" : undefined,
  });

export const previewSheet = (productId: string, qty: string) =>
  get<CostSheetPreview>(`/products/${productId}/sheet`, { qty });

export const listProcesses = (includeArchived = false) =>
  get<{ items: LaborProcess[]; total: number }>("/processes", {
    include_archived: includeArchived ? "true" : undefined,
  });

export const createProcess = (body: {
  name: string;
  note?: string | null;
  rate: string;
}) => send<LaborProcess>("POST", "/processes", body);

export const patchProcess = (
  processId: string,
  body: { name?: string; note?: string | null; is_archived?: boolean },
) => send<LaborProcess>("PATCH", `/processes/${processId}`, body);

export const addLaborRate = (
  processId: string,
  body: { rate: string; note?: string | null },
) => send<LaborRate>("POST", `/processes/${processId}/rates`, body);

export const listLaborRates = (processId: string) =>
  get<LaborRate[]>(`/processes/${processId}/rates`);

export const getProductLabor = (productId: string) =>
  get<{ product_id: string; lines: LaborLine[] }>(
    `/products/${productId}/labor`,
  );

export const replaceProductLabor = (
  productId: string,
  lines: { process_id: string; mode: LaborMode; qty: string }[],
) =>
  send<{ product_id: string; lines: LaborLine[] }>(
    "PUT",
    `/products/${productId}/labor`,
    { lines },
  );

export const setSalePrice = (
  productId: string,
  body: { unit_price: string; note?: string | null },
) => send<SalePrice>("POST", `/products/${productId}/sale-price`, body);

export const listSalePrices = (productId: string) =>
  get<{ items: SalePrice[]; total: number }>(
    `/products/${productId}/sale-prices`,
  );

export const setReferencePrice = (
  itemId: string,
  body: { unit_price: string; freight_per_unit?: string; source?: string },
) => send<unknown>("POST", `/items/${itemId}/reference-price`, body);

export const createSheet = (body: {
  product_id: string;
  batch_qty: string;
  sale_price_override?: string | null;
  note?: string | null;
}) => send<CostSheet>("POST", "/sheets", body);

export const listSheets = (productId?: string) =>
  get<{ items: CostSheet[]; total: number }>("/sheets", {
    product_id: productId,
  });

export const getSheet = (sheetId: string) =>
  get<CostSheetDetail>(`/sheets/${sheetId}`);

export const shareSheet = (
  sheetId: string,
  body: {
    recipient_user_ids: number[];
    share_mode: ShareMode;
    message?: string | null;
  },
) => send<ShareResult>("POST", `/sheets/${sheetId}/share`, body);

/** 缺价时后端一律给 null。**绝不能在这里退回 0**——一个看着完整的假总价会被拿去报价。 */
export const money = (value: string | null | undefined) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

export const qty = (value: string | null | undefined) => {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isInteger(n) ? String(n) : String(n);
};

export const percent = (value: string | null | undefined) =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;

export const BASIS_LABEL: Record<Basis, string> = {
  actual: "权威",
  estimate: "预估",
};

export const LABOR_MODE_LABEL: Record<LaborMode, string> = {
  per_unit: "每件",
  per_batch: "每批",
};
