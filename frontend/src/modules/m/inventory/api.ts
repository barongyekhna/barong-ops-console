"use client";

// M 系列制造库存的接口层。请求统一走 `lib/api.ts`。
//
// 这个模块是「结构化 detail」的典型:负库存被后端拦死时返回 409,
// detail 里带**逐项缺口清单**,对话框要按行渲染出来给人看。
// 收口前这份清单是本文件自己从响应里挖的;收口后由 `ApiError.detail` 带出来
// —— 那个字段就是为这类场景补的(以前 apiRequest 解析完就丢了)。

import { ApiError, apiRequest } from "@/lib/api";

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
  group_id: string | null;
  group_code: string | null;
  group_name: string | null;
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

/** 编码组:成品的「系列」/ 物料的「大类」。成品 TBL-001（三位）、物料 PK-0001（四位）。 */
export type CodeGroup = {
  id: string;
  kind: Kind;
  code: string;
  name: string;
  next_no: number;
  is_archived: boolean;
  item_count: number;
};

export const GROUP_LABEL: Record<Kind, string> = { product: "系列", part: "大类" };

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

/**
 * 把 `ApiError` 翻回本模块原有的两种错误形态。
 *
 * 收口只换传输层,**不改调用方看到的错误**:dialogs.tsx 里 `err instanceof
 * ShortageError` 那条分支要照常命中,FastAPI 422 也要照常显示第一条 msg
 * 而不是一句笼统的状态兜底。
 */
function rethrow(error: unknown): never {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  const detail = error.detail;
  if (
    error.status === 409 &&
    detail &&
    typeof detail === "object" &&
    Array.isArray((detail as { shortages?: unknown }).shortages)
  ) {
    const shortage = detail as { message?: string; shortages: RequirementRow[] };
    throw new ShortageError(shortage.message || "库存不足", shortage.shortages);
  }
  if (Array.isArray(detail)) {
    // FastAPI 422 校验错误:detail 是一个数组,第一条的 msg 才是人话。
    const first = detail[0] as { msg?: string } | undefined;
    throw new Error(first?.msg || `${LABEL}（${error.status}）`);
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
  return apiRequest<T>(`/mfg${path}${qs ? `?${qs}` : ""}`).catch(rethrow);
}

function send<T>(method: "POST" | "PATCH" | "PUT", path: string, body: unknown) {
  return apiRequest<T>(`/mfg${path}`, { body, method }).catch(rethrow);
}

export const getContext = () => get<FactoryContext>("/context");

export const getStock = (kind?: Kind, includeArchived = false) =>
  get<{ items: StockRow[]; total: number }>("/stock", {
    kind,
    include_archived: includeArchived ? "true" : undefined,
  });

/** 自动编码给 group_id；手填给 code。二选一，后端校验。 */
export const createItem = (body: {
  kind: Kind;
  group_id?: string;
  code?: string;
  name: string;
  unit: string;
  note?: string;
}) => send<Item>("POST", "/items", body);

export const patchItem = (
  id: string,
  body: Partial<Pick<Item, "name" | "unit" | "note" | "is_archived" | "code">>,
) => send<Item>("PATCH", `/items/${id}`, body);

export const listCodeGroups = (kind?: Kind) =>
  get<{ items: CodeGroup[]; total: number }>("/code-groups", { kind });

export const createCodeGroup = (body: { kind: Kind; code: string; name: string }) =>
  send<CodeGroup>("POST", "/code-groups", body);

export const suggestGroupCode = (name: string) =>
  get<{ code: string; taken: boolean }>("/code-groups/suggest", { name });

export const previewNextCode = (groupId: string) =>
  get<{ group_id: string; code: string }>(`/code-groups/${groupId}/next-code`);

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
