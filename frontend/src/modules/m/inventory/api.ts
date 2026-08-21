"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "库存";

export type Kind = "part" | "product";
export type BomMode = "per_unit" | "per_carton";
export type DocType = "receipt" | "production" | "shipment" | "adjustment";

export type Item = {
  id: string;
  kind: Kind;
  code: string;
  name: string;
  unit: string;
  note: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
};

export type StockRow = Item & { stock: string; bom_line_count: number };

export type BomLine = {
  id: string;
  part_id: string;
  part_code: string;
  part_name: string;
  part_unit: string;
  mode: BomMode;
  qty: string;
  position: number;
};

export type Bom = { product_id: string; lines: BomLine[] };

export type RequirementRow = {
  item_id: string;
  code: string;
  name: string;
  unit: string;
  mode: BomMode;
  bom_qty: string;
  required: string;
  available: string;
  short: string;
};

export type ProductionPreview = {
  product_id: string;
  qty: string;
  requirements: RequirementRow[];
  feasible: boolean;
};

export type Movement = {
  id: string;
  document_id: string;
  doc_no: string;
  doc_type: DocType;
  item_id: string;
  item_code: string;
  item_name: string;
  item_unit: string;
  qty_delta: string;
  created_at: string;
};

export type Document = {
  id: string;
  doc_type: DocType;
  doc_no: string;
  actor_user_id: string;
  actor_name: string;
  note: string | null;
  payload_json: Record<string, unknown>;
  created_at: string;
};

export type DocumentDetail = Document & { movements: Movement[] };

export type FactoryContext = {
  factory_org_id: string;
  org_name: string;
  suggested_units: string[];
};

/** 负库存拦死时后端返回 409，detail 里带逐项缺口。 */
export class ShortageError extends Error {
  shortages: RequirementRow[];
  constructor(message: string, shortages: RequirementRow[]) {
    super(message);
    this.shortages = shortages;
  }
}

function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  let detail: unknown = "";
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // non-JSON body
  }
  if (
    response.status === 409 &&
    detail &&
    typeof detail === "object" &&
    Array.isArray((detail as { shortages?: unknown }).shortages)
  ) {
    const d = detail as { message?: string; shortages: RequirementRow[] };
    throw new ShortageError(d.message || "库存不足", d.shortages);
  }
  if (Array.isArray(detail)) {
    // FastAPI 422 校验错误
    const first = detail[0] as { msg?: string } | undefined;
    throw new Error(first?.msg || `${LABEL}（${response.status}）`);
  }
  throw new Error(
    typeof detail === "string" && detail ? detail : `${LABEL}（${response.status}）`,
  );
}

function get<T>(path: string, params?: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") {
      query.set(key, value);
    }
  }
  const qs = query.toString();
  return fetch(`${API_PROXY_BASE}/mfg${path}${qs ? `?${qs}` : ""}`, {
    cache: "no-store",
    headers: buildHeaders(),
  }).then((r) => readJson<T>(r));
}

function send<T>(method: "POST" | "PATCH" | "PUT", path: string, body: unknown) {
  return fetch(`${API_PROXY_BASE}/mfg${path}`, {
    method,
    cache: "no-store",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  }).then((r) => readJson<T>(r));
}

export const getContext = () => get<FactoryContext>("/context");

export const getStock = (kind?: Kind, includeArchived = false) =>
  get<{ items: StockRow[]; total: number }>("/stock", {
    kind,
    include_archived: includeArchived ? "true" : undefined,
  });

export const createItem = (body: {
  kind: Kind;
  code: string;
  name: string;
  unit: string;
  note?: string;
}) => send<Item>("POST", "/items", body);

export const patchItem = (
  id: string,
  body: Partial<Pick<Item, "name" | "unit" | "note" | "is_archived">>,
) => send<Item>("PATCH", `/items/${id}`, body);

export const getBom = (productId: string) => get<Bom>(`/items/${productId}/bom`);

export const putBom = (
  productId: string,
  lines: { part_id: string; mode: BomMode; qty: string }[],
) => send<Bom>("PUT", `/items/${productId}/bom`, { lines });

export const getItemMovements = (id: string, limit = 100) =>
  get<{ items: Movement[]; total: number }>(`/items/${id}/movements`, {
    limit: String(limit),
  });

export const previewProduction = (productId: string, qty: string) =>
  get<ProductionPreview>("/production/preview", { product_id: productId, qty });

export const postReceipt = (body: {
  lines: { item_id: string; qty: string }[];
  note?: string;
}) => send<Document>("POST", "/documents/receipt", body);

export const postProduction = (body: {
  product_id: string;
  qty: string;
  note?: string;
}) => send<Document>("POST", "/documents/production", body);

export const postShipment = (body: {
  product_id: string;
  qty: string;
  note?: string;
}) => send<Document>("POST", "/documents/shipment", body);

export const postAdjustment = (body: {
  item_id: string;
  qty_delta: string;
  reason: string;
}) => send<Document>("POST", "/documents/adjustment", body);

export const getDocuments = (params: {
  doc_type?: DocType;
  item_id?: string;
  limit?: number;
}) =>
  get<{ items: Document[]; total: number }>("/documents", {
    doc_type: params.doc_type,
    item_id: params.item_id,
    limit: String(params.limit ?? 100),
  });

export const getDocument = (id: string) => get<DocumentDetail>(`/documents/${id}`);

export const DOC_TYPE_LABEL: Record<DocType, string> = {
  receipt: "入库",
  production: "生产",
  shipment: "发货",
  adjustment: "盘点调整",
};

export const MODE_LABEL: Record<BomMode, string> = {
  per_unit: "每件消耗",
  per_carton: "每箱装",
};

/** 去掉 "400.000" 里没意义的小数零。 */
export function fmtQty(value: string | number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return String(value);
  }
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
}
