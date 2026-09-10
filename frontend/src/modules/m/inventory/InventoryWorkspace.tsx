"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Dialog, QtyClass } from "./Dialog";
import styles from "./Inventory.module.css";
import {
  type DocType,
  type DocumentDetail,
  type FactoryContext,
  type Item,
  type Movement,
  type StockRow,
  type Document as MfgDocument,
  DOC_TYPE_LABEL,
  fmtQty,
  getContext,
  getDocument,
  getDocuments,
  getItemMovements,
  getStock,
  patchItem,
} from "./api";
import {
  AdjustmentDialog,
  BomDialog,
  ItemDialog,
  ProductionDialog,
  ReceiptDialog,
  ShipmentDialog,
} from "./dialogs";

type Tab = "parts" | "products" | "documents";

type Modal =
  | { kind: "new-part" }
  | { kind: "new-product" }
  | { kind: "bom"; product: StockRow }
  | { kind: "receipt"; itemId?: string }
  | { kind: "production"; productId?: string }
  | { kind: "shipment"; productId?: string }
  | { kind: "adjustment"; itemId?: string }
  | { kind: "movements"; item: StockRow }
  | { kind: "document"; id: string }
  | null;

function fmtTime(value: string) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString("zh-CN", { hour12: false });
}

export function InventoryWorkspace() {
  const [tab, setTab] = useState<Tab>("parts");
  const [context, setContext] = useState<FactoryContext | null>(null);
  const [rows, setRows] = useState<StockRow[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const refresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([context ? Promise.resolve(context) : getContext(), getStock(undefined, true)])
      .then(([ctx, stock]) => {
        if (cancelled) return;
        setContext(ctx);
        setRows(stock.items);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // context 只拉一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  const parts = useMemo(() => rows.filter((r) => r.kind === "part" && !r.is_archived), [rows]);
  const products = useMemo(() => rows.filter((r) => r.kind === "product" && !r.is_archived), [rows]);
  const active = useMemo(() => rows.filter((r) => !r.is_archived), [rows]);

  const visible = useMemo(() => {
    const kind = tab === "parts" ? "part" : "product";
    const q = search.trim().toLowerCase();
    return rows.filter(
      (r) =>
        r.kind === kind &&
        (showArchived || !r.is_archived) &&
        (!q || r.code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)),
    );
  }, [rows, tab, search, showArchived]);

  const closeAndRefresh = useCallback(() => {
    setModal(null);
    refresh();
  }, [refresh]);

  const toggleArchive = async (item: Item) => {
    try {
      await patchItem(item.id, { is_archived: !item.is_archived });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (error && !context) {
    return <div className={styles.error}>{error}</div>;
  }

  return (
    <div className={styles.workspace}>
      <div className={styles.topbar}>
        <div className={styles.tabs}>
          <button type="button" className={styles.tab} data-active={tab === "parts"} onClick={() => setTab("parts")}>
            物料 · {parts.length}
          </button>
          <button type="button" className={styles.tab} data-active={tab === "products"} onClick={() => setTab("products")}>
            成品 · {products.length}
          </button>
          <button type="button" className={styles.tab} data-active={tab === "documents"} onClick={() => setTab("documents")}>
            单据
          </button>
        </div>
        <span className={styles.factory}>{context?.org_name ?? ""}{loading ? " · 刷新中…" : ""}</span>
      </div>

      {error ? <div className={styles.error}>{error}</div> : null}

      {tab === "documents" ? (
        <DocumentsPanel onOpen={(id) => setModal({ kind: "document", id })} refreshTick={refreshTick} />
      ) : (
        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <div className={styles.filters}>
              <input
                className={styles.input}
                placeholder="搜编码 / 名称"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <label className={styles.muted}>
                <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 显示已归档
              </label>
            </div>
            <div className={styles.actions}>
              {tab === "parts" ? (
                <>
                  <button type="button" className={styles.btn} onClick={() => setModal({ kind: "new-part" })}>+ 新建物料</button>
                  <button type="button" className={styles.btnPrimary} disabled={active.length === 0} onClick={() => setModal({ kind: "receipt" })}>入库</button>
                </>
              ) : (
                <>
                  <button type="button" className={styles.btn} onClick={() => setModal({ kind: "new-product" })}>+ 新建成品</button>
                  <button type="button" className={styles.btnPrimary} disabled={products.length === 0} onClick={() => setModal({ kind: "production" })}>生产</button>
                  <button type="button" className={styles.btnPrimary} disabled={products.length === 0} onClick={() => setModal({ kind: "shipment" })}>发货</button>
                </>
              )}
              <button type="button" className={styles.btn} disabled={active.length === 0} onClick={() => setModal({ kind: "adjustment" })}>盘点调整</button>
            </div>
          </div>

          {visible.length === 0 ? (
            <div className={styles.empty}>
              {tab === "parts" ? "还没有物料。先新建物料，再入库。" : "还没有成品。新建成品后填写配件清单，才能生产。"}
            </div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>编码</th>
                    <th>{tab === "products" ? "系列" : "大类"}</th>
                    <th>名称</th>
                    <th className={styles.num}>当前库存</th>
                    <th>单位</th>
                    {tab === "products" ? <th>配件清单</th> : null}
                    <th>备注</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr key={row.id} data-clickable="true" onClick={() => setModal({ kind: "movements", item: row })}>
                      <td><span className={styles.code}>{row.code}</span>{row.is_archived ? <> <span className={styles.tagWarn}>已归档</span></> : null}</td>
                      <td className={styles.muted}>{row.group_name ?? "—"}</td>
                      <td>{row.name}</td>
                      <td className={`${styles.num} ${QtyClass(row.stock)}`}>{fmtQty(row.stock)}</td>
                      <td className={styles.muted}>{row.unit}</td>
                      {tab === "products" ? (
                        <td>
                          {row.bom_line_count > 0 ? (
                            <span className={styles.tag}>{row.bom_line_count} 行</span>
                          ) : (
                            <span className={styles.tagWarn}>未填写</span>
                          )}
                        </td>
                      ) : null}
                      <td className={styles.muted}>{row.note ?? ""}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className={styles.actions}>
                          {tab === "products" ? (
                            <>
                              <button type="button" className={styles.btnGhost} onClick={() => setModal({ kind: "bom", product: row })}>配件清单</button>
                              <button type="button" className={styles.btnGhost} disabled={row.is_archived || row.bom_line_count === 0} onClick={() => setModal({ kind: "production", productId: row.id })}>生产</button>
                              <button type="button" className={styles.btnGhost} disabled={row.is_archived} onClick={() => setModal({ kind: "shipment", productId: row.id })}>发货</button>
                            </>
                          ) : (
                            <button type="button" className={styles.btnGhost} disabled={row.is_archived} onClick={() => setModal({ kind: "receipt", itemId: row.id })}>入库</button>
                          )}
                          <button type="button" className={styles.btnGhost} disabled={row.is_archived} onClick={() => setModal({ kind: "adjustment", itemId: row.id })}>调整</button>
                          <button type="button" className={styles.btnGhost} onClick={() => toggleArchive(row)}>{row.is_archived ? "恢复" : "归档"}</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {modal?.kind === "new-part" ? <ItemDialog kind="part" units={context?.suggested_units ?? []} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "new-product" ? <ItemDialog kind="product" units={context?.suggested_units ?? []} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "bom" ? <BomDialog product={modal.product} parts={parts} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "receipt" ? <ReceiptDialog items={active} initialItemId={modal.itemId} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "production" ? <ProductionDialog products={products.filter((p) => p.bom_line_count > 0)} initialProductId={modal.productId} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "shipment" ? <ShipmentDialog products={products} initialProductId={modal.productId} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "adjustment" ? <AdjustmentDialog items={active} initialItemId={modal.itemId} onClose={() => setModal(null)} onDone={closeAndRefresh} /> : null}
      {modal?.kind === "movements" ? <MovementsDialog item={modal.item} onClose={() => setModal(null)} onOpenDocument={(id) => setModal({ kind: "document", id })} /> : null}
      {modal?.kind === "document" ? <DocumentDialog id={modal.id} onClose={() => setModal(null)} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------- 流水

function MovementsDialog({
  item,
  onClose,
  onOpenDocument,
}: {
  item: StockRow;
  onClose: () => void;
  onOpenDocument: (id: string) => void;
}) {
  const [rows, setRows] = useState<Movement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getItemMovements(item.id, 200)
      .then((r) => setRows(r.items))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [item.id]);
  return (
    <Dialog title={`流水 · ${item.code} ${item.name}（现有 ${fmtQty(item.stock)} ${item.unit}）`} onClose={onClose}>
      {error ? <div className={styles.error}>{error}</div> : null}
      {rows === null && !error ? <div className={styles.muted}>加载中…</div> : null}
      {rows && rows.length === 0 ? <div className={styles.empty}>还没有任何流水。</div> : null}
      {rows && rows.length > 0 ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>时间</th>
                <th>单据</th>
                <th>类型</th>
                <th className={styles.num}>变动</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((mv) => (
                <tr key={mv.id} data-clickable="true" onClick={() => onOpenDocument(mv.document_id)}>
                  <td className={styles.muted}>{fmtTime(mv.created_at)}</td>
                  <td><span className={styles.code}>{mv.doc_no}</span></td>
                  <td>{DOC_TYPE_LABEL[mv.doc_type]}</td>
                  <td className={`${styles.num} ${QtyClass(mv.qty_delta)}`}>
                    {Number(mv.qty_delta) > 0 ? "+" : ""}{fmtQty(mv.qty_delta)} {mv.item_unit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Dialog>
  );
}

// ---------------------------------------------------------------- 单据列表

function DocumentsPanel({ onOpen, refreshTick }: { onOpen: (id: string) => void; refreshTick: number }) {
  const [docType, setDocType] = useState<DocType | "">("");
  const [docs, setDocs] = useState<MfgDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getDocuments({ doc_type: docType || undefined, limit: 200 })
      .then((r) => setDocs(r.items))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [docType, refreshTick]);
  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>单据</h2>
        <div className={styles.filters}>
          {(["", "receipt", "production", "shipment", "adjustment"] as const).map((t) => (
            <button key={t || "all"} type="button" className={styles.tab} data-active={docType === t} onClick={() => setDocType(t)}>
              {t ? DOC_TYPE_LABEL[t] : "全部"}
            </button>
          ))}
        </div>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}
      {docs === null && !error ? <div className={styles.muted}>加载中…</div> : null}
      {docs && docs.length === 0 ? <div className={styles.empty}>还没有单据。</div> : null}
      {docs && docs.length > 0 ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>时间</th>
                <th>单号</th>
                <th>类型</th>
                <th>摘要</th>
                <th>操作人</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id} data-clickable="true" onClick={() => onOpen(doc.id)}>
                  <td className={styles.muted}>{fmtTime(doc.created_at)}</td>
                  <td><span className={styles.code}>{doc.doc_no}</span></td>
                  <td>{DOC_TYPE_LABEL[doc.doc_type]}</td>
                  <td>{summarize(doc)}</td>
                  <td className={styles.muted}>{doc.actor_name}</td>
                  <td className={styles.muted}>{doc.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function summarize(doc: MfgDocument): string {
  const p = doc.payload_json as Record<string, unknown>;
  if (doc.doc_type === "receipt") {
    const lines = (p.lines ?? []) as { code: string; qty: string; unit: string }[];
    return lines.map((l) => `${l.code} +${fmtQty(l.qty)} ${l.unit}`).join("，");
  }
  if (doc.doc_type === "production" || doc.doc_type === "shipment") {
    const prod = p.product as { code: string; name: string; qty: string; unit: string } | undefined;
    return prod ? `${prod.code} ${prod.name} ${doc.doc_type === "production" ? "+" : "−"}${fmtQty(prod.qty)} ${prod.unit}` : "";
  }
  const item = p.item as { code: string; name: string; unit: string } | undefined;
  return item ? `${item.code} ${item.name} ${Number(p.qty_delta) > 0 ? "+" : ""}${fmtQty(String(p.qty_delta))} ${item.unit}` : "";
}

// ---------------------------------------------------------------- 单据详情

function DocumentDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getDocument(id)
      .then(setDoc)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [id]);
  const snapshot = (doc?.payload_json as Record<string, unknown> | undefined)?.bom_snapshot as
    | { code: string; name: string; unit: string; mode: string; bom_qty: string; consumed: string }[]
    | undefined;
  return (
    <Dialog title={doc ? `${DOC_TYPE_LABEL[doc.doc_type]} ${doc.doc_no}` : "单据"} onClose={onClose}>
      {error ? <div className={styles.error}>{error}</div> : null}
      {!doc && !error ? <div className={styles.muted}>加载中…</div> : null}
      {doc ? (
        <div className={styles.form}>
          <dl className={styles.kv}>
            <dt>时间</dt><dd>{fmtTime(doc.created_at)}</dd>
            <dt>操作人</dt><dd>{doc.actor_name}</dd>
            <dt>摘要</dt><dd>{summarize(doc)}</dd>
            {doc.note ? (<><dt>备注</dt><dd>{doc.note}</dd></>) : null}
          </dl>
          {snapshot ? (
            <>
              <div className={styles.muted}>当时的配件清单（冻结快照，改配方不影响历史单据）</div>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead><tr><th>物料</th><th>算法</th><th className={styles.num}>消耗</th></tr></thead>
                  <tbody>
                    {snapshot.map((s) => (
                      <tr key={s.code}>
                        <td><span className={styles.code}>{s.code}</span> {s.name}</td>
                        <td className={styles.muted}>{s.mode === "per_carton" ? `每箱装 ${fmtQty(s.bom_qty)}` : `每件消耗 ${fmtQty(s.bom_qty)}`}</td>
                        <td className={`${styles.num} ${styles.neg}`}>−{fmtQty(s.consumed)} {s.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          <div className={styles.muted}>流水</div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>物料 / 成品</th><th className={styles.num}>变动</th></tr></thead>
              <tbody>
                {doc.movements.map((mv) => (
                  <tr key={mv.id}>
                    <td><span className={styles.code}>{mv.item_code}</span> {mv.item_name}</td>
                    <td className={`${styles.num} ${QtyClass(mv.qty_delta)}`}>{Number(mv.qty_delta) > 0 ? "+" : ""}{fmtQty(mv.qty_delta)} {mv.item_unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}
