"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Dialog } from "./Dialog";
import styles from "./Inventory.module.css";
import {
  type BomMode,
  type Kind,
  type ProductionPreview,
  type RequirementRow,
  type StockRow,
  MODE_LABEL,
  ShortageError,
  createItem,
  fmtQty,
  getBom,
  postAdjustment,
  postProduction,
  postReceipt,
  postShipment,
  previewProduction,
  putBom,
} from "./api";

type Done = () => void;

function useSubmit(run: () => Promise<void>, onDone: Done) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shortages, setShortages] = useState<RequirementRow[] | null>(null);
  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    setShortages(null);
    try {
      await run();
      onDone();
    } catch (err) {
      if (err instanceof ShortageError) {
        setShortages(err.shortages);
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [run, onDone]);
  return { busy, error, shortages, submit };
}

function ShortageTable({ rows }: { rows: RequirementRow[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>物料</th>
            <th>算法</th>
            <th className={styles.num}>需要</th>
            <th className={styles.num}>现有</th>
            <th className={styles.num}>缺口</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.item_id}>
              <td>
                <span className={styles.code}>{row.code}</span> {row.name}
              </td>
              <td className={styles.muted}>
                {MODE_LABEL[row.mode]} {fmtQty(row.bom_qty)}
              </td>
              <td className={styles.num}>
                {fmtQty(row.required)} {row.unit}
              </td>
              <td className={styles.num}>{fmtQty(row.available)}</td>
              <td className={`${styles.num} ${Number(row.short) > 0 ? styles.neg : styles.pos}`}>
                {Number(row.short) > 0 ? `缺 ${fmtQty(row.short)}` : "够"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- 新建物料/成品

export function ItemDialog({
  kind,
  units,
  onClose,
  onDone,
}: {
  kind: Kind;
  units: string[];
  onClose: () => void;
  onDone: Done;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState(kind === "product" ? "套" : "个");
  const [note, setNote] = useState("");
  const { busy, error, submit } = useSubmit(
    useCallback(
      () => createItem({ kind, code, name, unit, note: note || undefined }).then(() => undefined),
      [kind, code, name, unit, note],
    ),
    onDone,
  );
  const title = kind === "product" ? "新建成品" : "新建物料";
  const kindHint =
    kind === "product"
      ? "正在新建「成品」（可配 BOM、能被生产）。要建原料/配件请到「物料」页新建。"
      : "正在新建「物料」（原料/配件，用于成品的 BOM）。要建成品请到「成品」页新建。";
  return (
    <Dialog title={title} onClose={onClose}>
      <div className={styles.form}>
        <p className={styles.label} style={{ opacity: 0.75 }}>{kindHint}</p>
        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>编码（唯一）</span>
            <input className={styles.input} value={code} onChange={(e) => setCode(e.target.value)} placeholder="如 TOP-001" />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>名称</span>
            <input className={styles.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="如 桌面" />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>单位（自选，不换算）</span>
            <input className={styles.input} list="mfg-units" value={unit} onChange={(e) => setUnit(e.target.value)} />
            <datalist id="mfg-units">
              {units.map((u) => (
                <option key={u} value={u} />
              ))}
            </datalist>
          </label>
        </div>
        <label className={styles.field}>
          <span className={styles.label}>备注</span>
          <textarea className={styles.textarea} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={busy || !code.trim() || !name.trim() || !unit.trim()}
            onClick={submit}
          >
            {busy ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- BOM 编辑

type DraftLine = { part_id: string; mode: BomMode; qty: string };

export function BomDialog({
  product,
  parts,
  onClose,
  onDone,
}: {
  product: StockRow;
  parts: StockRow[];
  onClose: () => void;
  onDone: Done;
}) {
  const [lines, setLines] = useState<DraftLine[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    getBom(product.id)
      .then((bom) =>
        setLines(bom.lines.map((l) => ({ part_id: l.part_id, mode: l.mode, qty: fmtQtyPlain(l.qty) }))),
      )
      .catch((err) => setLoadError(err instanceof Error ? err.message : String(err)));
  }, [product.id]);

  const partById = useMemo(() => new Map(parts.map((p) => [p.id, p])), [parts]);
  const { busy, error, submit } = useSubmit(
    useCallback(
      () => putBom(product.id, (lines ?? []).filter((l) => l.part_id)).then(() => undefined),
      [product.id, lines],
    ),
    onDone,
  );
  const invalid = (lines ?? []).some(
    (l) => !l.part_id || !(Number(l.qty) > 0),
  );
  const update = (index: number, patch: Partial<DraftLine>) =>
    setLines((prev) => (prev ?? []).map((l, i) => (i === index ? { ...l, ...patch } : l)));

  return (
    <Dialog title={`配件清单 · ${product.code} ${product.name}`} onClose={onClose}>
      <div className={styles.form}>
        <p className={styles.hint}>
          「每件消耗」= 生产 1 {product.unit}用掉多少；「每箱装」= 多少{product.unit}装 1 个，不整箱按整箱算（105 件 ÷ 10 件/箱 = 11 箱）。
        </p>
        {loadError ? <div className={styles.error}>{loadError}</div> : null}
        {lines === null && !loadError ? <div className={styles.muted}>加载中…</div> : null}
        {lines ? (
          <div className={styles.lineList}>
            {lines.map((line, index) => {
              const part = partById.get(line.part_id);
              return (
                <div key={index} className={styles.line}>
                  <select
                    className={styles.select}
                    value={line.part_id}
                    onChange={(e) => update(index, { part_id: e.target.value })}
                  >
                    <option value="">选择物料…</option>
                    {parts.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.code} · {p.name}（{p.unit}）
                      </option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={line.mode}
                    onChange={(e) => update(index, { mode: e.target.value as BomMode })}
                  >
                    <option value="per_unit">每件消耗</option>
                    <option value="per_carton">每箱装</option>
                  </select>
                  <input
                    className={styles.inputSm}
                    inputMode="decimal"
                    value={line.qty}
                    onChange={(e) => update(index, { qty: e.target.value })}
                  />
                  <span className={styles.muted}>
                    {line.mode === "per_unit" ? part?.unit ?? "" : `${product.unit}/箱`}
                  </span>
                  <button
                    type="button"
                    className={styles.btnGhost}
                    onClick={() => setLines((prev) => (prev ?? []).filter((_, i) => i !== index))}
                  >
                    删除
                  </button>
                </div>
              );
            })}
            <div>
              <button
                type="button"
                className={styles.btn}
                onClick={() => setLines((prev) => [...(prev ?? []), { part_id: "", mode: "per_unit", qty: "1" }])}
              >
                + 加一行
              </button>
            </div>
          </div>
        ) : null}
        {error ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button type="button" className={styles.btnPrimary} disabled={busy || lines === null || invalid} onClick={submit}>
            {busy ? "保存中…" : "保存配件清单"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function fmtQtyPlain(value: string) {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

// ---------------------------------------------------------------- 生产

export function ProductionDialog({
  products,
  initialProductId,
  onClose,
  onDone,
}: {
  products: StockRow[];
  initialProductId?: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [productId, setProductId] = useState(initialProductId ?? products[0]?.id ?? "");
  const [qty, setQty] = useState("1");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<ProductionPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!productId || !(Number(qty) > 0)) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      previewProduction(productId, qty)
        .then((p) => {
          if (!cancelled) {
            setPreview(p);
            setPreviewError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setPreview(null);
            setPreviewError(err instanceof Error ? err.message : String(err));
          }
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [productId, qty]);

  const { busy, error, shortages, submit } = useSubmit(
    useCallback(
      () => postProduction({ product_id: productId, qty, note: note || undefined }).then(() => undefined),
      [productId, qty, note],
    ),
    onDone,
  );
  const product = products.find((p) => p.id === productId);

  return (
    <Dialog title="生产入账" onClose={onClose}>
      <div className={styles.form}>
        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>成品</span>
            <select className={styles.select} value={productId} onChange={(e) => setProductId(e.target.value)}>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}（现有 {fmtQty(p.stock)} {p.unit}）
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            <span className={styles.label}>生产数量{product ? `（${product.unit}）` : ""}</span>
            <input className={styles.input} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
        </div>
        <label className={styles.field}>
          <span className={styles.label}>备注</span>
          <input className={styles.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="批次 / 班组 / 任何想记的" />
        </label>
        {previewError ? <div className={styles.error}>{previewError}</div> : null}
        {preview ? (
          <>
            <div className={preview.feasible ? styles.notice : styles.error}>
              {preview.feasible ? "物料足够，提交后按下表扣减：" : "物料不足，无法生产（负库存拦死，请先入库）："}
            </div>
            <ShortageTable rows={preview.requirements} />
          </>
        ) : null}
        {shortages ? <ShortageTable rows={shortages} /> : null}
        {error && !shortages ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={busy || !preview || !preview.feasible}
            onClick={submit}
          >
            {busy ? "提交中…" : `确认生产 ${fmtQty(qty || 0)} ${product?.unit ?? ""}`}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 发货

export function ShipmentDialog({
  products,
  initialProductId,
  onClose,
  onDone,
}: {
  products: StockRow[];
  initialProductId?: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [productId, setProductId] = useState(initialProductId ?? products[0]?.id ?? "");
  const [qty, setQty] = useState("1");
  const [note, setNote] = useState("");
  const product = products.find((p) => p.id === productId);
  const available = Number(product?.stock ?? 0);
  const over = Number(qty) > available;
  const { busy, error, submit } = useSubmit(
    useCallback(
      () => postShipment({ product_id: productId, qty, note: note || undefined }).then(() => undefined),
      [productId, qty, note],
    ),
    onDone,
  );
  return (
    <Dialog title="发货出账" onClose={onClose}>
      <div className={styles.form}>
        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>成品</span>
            <select className={styles.select} value={productId} onChange={(e) => setProductId(e.target.value)}>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}（现有 {fmtQty(p.stock)} {p.unit}）
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            <span className={styles.label}>发货数量{product ? `（${product.unit}）` : ""}</span>
            <input className={styles.input} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
        </div>
        <label className={styles.field}>
          <span className={styles.label}>备注</span>
          <input className={styles.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="客户 / 运单号 / 任何想记的" />
        </label>
        {over ? (
          <div className={styles.error}>
            现有 {fmtQty(available)} {product?.unit}，不够发 {fmtQty(qty)}。
          </div>
        ) : null}
        {error ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button type="button" className={styles.btnPrimary} disabled={busy || !productId || !(Number(qty) > 0) || over} onClick={submit}>
            {busy ? "提交中…" : "确认发货"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 入库

export function ReceiptDialog({
  items,
  initialItemId,
  onClose,
  onDone,
}: {
  items: StockRow[];
  initialItemId?: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [lines, setLines] = useState<{ item_id: string; qty: string }[]>([
    { item_id: initialItemId ?? "", qty: "" },
  ]);
  const [note, setNote] = useState("");
  const valid = lines.filter((l) => l.item_id && Number(l.qty) > 0);
  const { busy, error, submit } = useSubmit(
    useCallback(
      () => postReceipt({ lines: valid, note: note || undefined }).then(() => undefined),
      [valid, note],
    ),
    onDone,
  );
  const update = (index: number, patch: Partial<{ item_id: string; qty: string }>) =>
    setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  return (
    <Dialog title="采购 / 自产入库" onClose={onClose}>
      <div className={styles.form}>
        <div className={styles.lineList}>
          {lines.map((line, index) => {
            const item = items.find((i) => i.id === line.item_id);
            return (
              <div key={index} className={styles.line}>
                <select className={styles.select} value={line.item_id} onChange={(e) => update(index, { item_id: e.target.value })}>
                  <option value="">选择物料 / 成品…</option>
                  {items.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.kind === "product" ? "[成品] " : ""}{i.code} · {i.name}（现有 {fmtQty(i.stock)} {i.unit}）
                    </option>
                  ))}
                </select>
                <input className={styles.inputSm} inputMode="decimal" placeholder="数量" value={line.qty} onChange={(e) => update(index, { qty: e.target.value })} />
                <span className={styles.muted}>{item?.unit ?? ""}</span>
                <span />
                <button type="button" className={styles.btnGhost} onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}>
                  删除
                </button>
              </div>
            );
          })}
          <div>
            <button type="button" className={styles.btn} onClick={() => setLines((prev) => [...prev, { item_id: "", qty: "" }])}>
              + 加一行
            </button>
          </div>
        </div>
        <label className={styles.field}>
          <span className={styles.label}>备注</span>
          <input className={styles.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="供应商 / 采购单号 / 任何想记的" />
        </label>
        {error ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button type="button" className={styles.btnPrimary} disabled={busy || valid.length === 0} onClick={submit}>
            {busy ? "提交中…" : `确认入库（${valid.length} 行）`}
          </button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 盘点调整

export function AdjustmentDialog({
  items,
  initialItemId,
  onClose,
  onDone,
}: {
  items: StockRow[];
  initialItemId?: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [itemId, setItemId] = useState(initialItemId ?? items[0]?.id ?? "");
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const item = items.find((i) => i.id === itemId);
  const after = Number(item?.stock ?? 0) + Number(delta || 0);
  const { busy, error, submit } = useSubmit(
    useCallback(
      () => postAdjustment({ item_id: itemId, qty_delta: delta, reason }).then(() => undefined),
      [itemId, delta, reason],
    ),
    onDone,
  );
  return (
    <Dialog title="盘点调整" onClose={onClose}>
      <div className={styles.form}>
        <p className={styles.hint}>账实不符时用这里，正数加、负数减；原因必填，会永久记在单据上。调整后不能变成负数。</p>
        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>物料 / 成品</span>
            <select className={styles.select} value={itemId} onChange={(e) => setItemId(e.target.value)}>
              {items.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.kind === "product" ? "[成品] " : ""}{i.code} · {i.name}（现有 {fmtQty(i.stock)} {i.unit}）
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            <span className={styles.label}>调整量（± {item?.unit ?? ""}）</span>
            <input className={styles.input} inputMode="decimal" value={delta} onChange={(e) => setDelta(e.target.value)} placeholder="如 -10" />
          </label>
        </div>
        <label className={styles.field}>
          <span className={styles.label}>原因（必填）</span>
          <textarea className={styles.textarea} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {delta && item ? (
          <div className={after < 0 ? styles.error : styles.notice}>
            调整后：{fmtQty(item.stock)} → {fmtQty(after)} {item.unit}
          </div>
        ) : null}
        {error ? <div className={styles.error}>{error}</div> : null}
        <div className={styles.footer}>
          <button type="button" className={styles.btn} onClick={onClose}>取消</button>
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={busy || !itemId || !reason.trim() || !(Number(delta) !== 0) || after < 0}
            onClick={submit}
          >
            {busy ? "提交中…" : "确认调整"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
