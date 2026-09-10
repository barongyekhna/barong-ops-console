"use client";

/**
 * M 系列 · 出货成本明细。
 *
 * 两个页签:产品成本(列表 → 点开详情)和工序库。详情页是这个模块的主体:BOM 物料
 * 逐行带单价与运费,人工单独一个板块,表尾像 Excel 一样自动合计,厂长在成本之上手
 * 填出厂价,底部一键通过 C19 把快照发给贸易公司的人。
 *
 * 一条死规矩贯穿全文件:**缺价绝不显示成 0**。后端缺价时给 null,这里一律渲染成
 * `—` 并把缺了几项写在旁边。一个看着完整的假总价会被直接拿去报价。
 */

import { useCallback, useEffect, useState } from "react";

import base from "../inventory/Inventory.module.css";
import styles from "./Cost.module.css";
import {
  BASIS_LABEL,
  type CostLine,
  type CostSheetPreview,
  type LaborLine,
  type LaborProcess,
  type ProductCostRow,
  createProcess,
  createSheet,
  getProductLabor,
  listProcesses,
  listProductCosts,
  money,
  percent,
  previewSheet,
  qty as fmtQty,
  replaceProductLabor,
  setSalePrice,
} from "./api";
import { ShareDialog } from "./ShareDialog";
import { LaborEditor } from "./LaborEditor";

type Tab = "products" | "processes";

export function CostWorkspace() {
  const [tab, setTab] = useState<Tab>("products");
  const [rows, setRows] = useState<ProductCostRow[]>([]);
  const [processes, setProcesses] = useState<LaborProcess[]>([]);
  const [openProduct, setOpenProduct] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshTick, setRefreshTick] = useState(0);

  const refresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([listProductCosts(), listProcesses()])
      .then(([productList, processList]) => {
        if (cancelled) return;
        setRows(productList.items);
        setProcesses(processList.items);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "读取失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  if (openProduct) {
    return (
      <SheetDetail
        productId={openProduct}
        processes={processes}
        onBack={() => {
          setOpenProduct(null);
          refresh();
        }}
      />
    );
  }

  return (
    <div className={base.workspace}>
      <div className={base.topbar}>
        <div className={base.tabs}>
          <button
            className={base.tab}
            data-active={tab === "products"}
            onClick={() => setTab("products")}
            type="button"
          >
            产品成本 · {rows.length}
          </button>
          <button
            className={base.tab}
            data-active={tab === "processes"}
            onClick={() => setTab("processes")}
            type="button"
          >
            工序库 · {processes.length}
          </button>
        </div>
      </div>

      {error ? <p className={base.error}>{error}</p> : null}
      {loading ? <p className={base.muted}>读取中…</p> : null}

      {tab === "products" ? (
        <ProductTable rows={rows} onOpen={setOpenProduct} />
      ) : (
        <ProcessPanel processes={processes} onChanged={refresh} />
      )}
    </div>
  );
}

function ProductTable({
  rows,
  onOpen,
}: {
  rows: ProductCostRow[];
  onOpen: (productId: string) => void;
}) {
  if (!rows.length) {
    return (
      <p className={base.empty}>
        还没有成品。先去库存模块建成品并录好配件清单——这张表的上限就是配件清单的完整度。
      </p>
    );
  }
  return (
    <div className={base.panel}>
      <div className={base.tableWrap}>
        <table className={base.table}>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th className={base.num}>库存</th>
              <th className={base.num}>单位成本</th>
              <th className={base.num}>出厂价</th>
              <th className={base.num}>毛利率</th>
              <th>成色</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.product_id}
                data-clickable="true"
                onClick={() => onOpen(row.product_id)}
              >
                <td>
                  <span className={base.code}>{row.code}</span>
                </td>
                <td>{row.name}</td>
                <td className={base.num}>
                  {fmtQty(row.stock)} {row.unit}
                </td>
                <td className={base.num}>
                  {row.missing_price_count > 0 ? (
                    <span className={styles.missing}>
                      — · 缺价 {row.missing_price_count} 项
                    </span>
                  ) : (
                    money(row.unit_cost)
                  )}
                </td>
                <td className={base.num}>
                  {row.sale_price === null ? (
                    <span className={base.muted}>未定价</span>
                  ) : (
                    money(row.sale_price)
                  )}
                </td>
                <td className={base.num}>{percent(row.margin_rate)}</td>
                <td>
                  <span
                    className={row.basis === "actual" ? base.tag : base.tagWarn}
                  >
                    {BASIS_LABEL[row.basis]}
                  </span>
                  {row.bom_line_count === 0 ? (
                    <span className={base.tagWarn}>无配件清单</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SheetDetail({
  productId,
  processes,
  onBack,
}: {
  productId: string;
  processes: LaborProcess[];
  onBack: () => void;
}) {
  const [batchQty, setBatchQty] = useState("100");
  const [preview, setPreview] = useState<CostSheetPreview | null>(null);
  const [laborLines, setLaborLines] = useState<LaborLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [priceDraft, setPriceDraft] = useState("");
  const [shareSheetId, setShareSheetId] = useState<string | null>(null);
  const [editingLabor, setEditingLabor] = useState(false);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    const trimmed = batchQty.trim();
    if (!trimmed || Number(trimmed) <= 0) return;
    Promise.all([previewSheet(productId, trimmed), getProductLabor(productId)])
      .then(([sheet, labor]) => {
        if (cancelled) return;
        setPreview(sheet);
        setLaborLines(labor.lines);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "读取失败");
      });
    return () => {
      cancelled = true;
    };
  }, [productId, batchQty, tick]);

  const savePrice = async () => {
    const value = priceDraft.trim();
    if (!value) return;
    setBusy(true);
    try {
      await setSalePrice(productId, { unit_price: value });
      setPriceDraft("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "定价失败");
    } finally {
      setBusy(false);
    }
  };

  const freezeAndShare = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const sheet = await createSheet({
        product_id: productId,
        batch_qty: preview.batch_qty,
      });
      setShareSheetId(sheet.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "定稿失败");
    } finally {
      setBusy(false);
    }
  };

  if (!preview) {
    return (
      <div className={base.workspace}>
        <button className={base.btnGhost} onClick={onBack} type="button">
          ← 返回
        </button>
        {error ? <p className={base.error}>{error}</p> : null}
        <p className={base.muted}>读取中…</p>
      </div>
    );
  }

  const missing = preview.totals.missing_price_count;

  return (
    <div className={base.workspace}>
      <div className={base.topbar}>
        <button className={base.btnGhost} onClick={onBack} type="button">
          ← 返回
        </button>
        <div className={styles.headline}>
          <span className={base.code}>{preview.product_code}</span>
          <strong>{preview.product_name}</strong>
          <span
            className={preview.basis === "actual" ? base.tag : base.tagWarn}
          >
            {BASIS_LABEL[preview.basis]}
            {preview.source_doc_no ? ` · ${preview.source_doc_no}` : ""}
          </span>
        </div>
      </div>

      {error ? <p className={base.error}>{error}</p> : null}

      <div className={base.panel}>
        <div className={base.panelHead}>
          <span className={base.panelTitle}>本次数量</span>
          <input
            className={base.inputSm}
            inputMode="decimal"
            onChange={(event) => setBatchQty(event.target.value)}
            value={batchQty}
          />
          <span className={base.muted}>{preview.product_unit}</span>
          <span className={base.muted}>
            库存 {fmtQty(preview.stock)} {preview.product_unit}
          </span>
          <span className={preview.has_volatile ? base.tagWarn : base.tag}>
            有效期至 {preview.expires_on}
            {preview.has_volatile ? "（含波动料，7 天）" : "（30 天）"}
          </span>
        </div>
        {preview.basis === "actual" ? (
          <p className={base.hint}>
            这批货已经生产完，成本在生产那一刻就定死了。下面的明细是生产批次
            {preview.source_doc_no ? ` ${preview.source_doc_no}` : ""} 的真实用料，
            本次数量只影响「本单总额」一行。
          </p>
        ) : (
          <p className={base.hint}>
            还没有成品库存，下面是按当前物料批次价算的**预估**。真正生产之后，成本会
            按那一刻的实际用料重新定死。
          </p>
        )}
      </div>

      <MaterialTable lines={preview.materials} />

      <div className={base.panel}>
        <div className={base.panelHead}>
          <span className={base.panelTitle}>人工</span>
          <button
            className={base.btnGhost}
            onClick={() => setEditingLabor(true)}
            type="button"
          >
            编辑工序
          </button>
        </div>
        {preview.labor.length ? (
          <div className={base.tableWrap}>
            <table className={base.table}>
              <thead>
                <tr>
                  <th>工序</th>
                  <th>计价</th>
                  <th className={base.num}>用量</th>
                  <th className={base.num}>工价</th>
                  <th className={base.num}>小计</th>
                </tr>
              </thead>
              <tbody>
                {preview.labor.map((line, index) => (
                  <tr key={`labor-${index}-${line.name}`}>
                    <td>{line.name}</td>
                    <td>
                      {line.mode === "per_batch" ? "每批（摊销）" : "每件"}
                    </td>
                    <td className={base.num}>{fmtQty(line.qty)}</td>
                    <td className={base.num}>
                      {line.missing_price ? (
                        <span className={styles.missing}>未定工价</span>
                      ) : (
                        money(line.unit_price)
                      )}
                    </td>
                    <td className={base.num}>{money(line.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={base.empty}>
            这个产品还没挂工序。人工算 0 会让成本偏低，报价就会亏。
          </p>
        )}
      </div>

      <div className={base.panel}>
        <div className={base.panelHead}>
          <span className={base.panelTitle}>合计</span>
        </div>
        {missing > 0 ? (
          <p className={styles.missingBanner}>
            有 {missing} 项没有价格，合计拒绝出数。缺的那几行在上面标红了——
            补上入库单价，或给它记一条参考价。
          </p>
        ) : null}
        <dl className={styles.totals}>
          <Total label="物料成本" value={money(preview.totals.material_total)} />
          <Total label="运费" value={money(preview.totals.freight_total)} />
          <Total label="人工" value={money(preview.totals.labor_total)} />
          <Total
            emphasis
            label="单位总成本"
            value={money(preview.totals.unit_cost)}
          />
        </dl>

        <div className={styles.priceRow}>
          <label className={base.label} htmlFor="sale-price">
            出厂价（厂长填）
          </label>
          <span className={styles.currentPrice}>
            {preview.sale_price === null ? (
              <span className={base.muted}>未定价</span>
            ) : (
              money(preview.sale_price)
            )}
          </span>
          <input
            className={base.inputSm}
            id="sale-price"
            inputMode="decimal"
            onChange={(event) => setPriceDraft(event.target.value)}
            placeholder="改价"
            value={priceDraft}
          />
          <button
            className={base.btnPrimary}
            disabled={busy || !priceDraft.trim()}
            onClick={savePrice}
            type="button"
          >
            保存
          </button>
        </div>

        <dl className={styles.totals}>
          <Total label="单位毛利" value={money(preview.unit_margin)} />
          <Total label="毛利率" value={percent(preview.margin_rate)} />
          <Total
            emphasis
            label={`本单总额 × ${fmtQty(preview.batch_qty)}`}
            value={money(preview.batch_total)}
          />
        </dl>

        <div className={base.footer}>
          <button
            className={base.btnPrimary}
            disabled={busy || preview.sale_price === null}
            onClick={freezeAndShare}
            type="button"
          >
            定稿并分享
          </button>
          {preview.sale_price === null ? (
            <span className={base.hint}>
              先定出厂价再分享——贸易公司要的就是这个数。
            </span>
          ) : (
            <span className={base.hint}>
              定稿会把当前数字冻成快照，发出去的那份以后不会再变。
            </span>
          )}
        </div>
      </div>

      {shareSheetId ? (
        <ShareDialog
          onClose={() => {
            setShareSheetId(null);
            reload();
          }}
          sheetId={shareSheetId}
        />
      ) : null}

      {editingLabor ? (
        <LaborEditor
          lines={laborLines}
          onClose={() => setEditingLabor(false)}
          onSave={async (lines) => {
            await replaceProductLabor(productId, lines);
            setEditingLabor(false);
            reload();
          }}
          processes={processes}
        />
      ) : null}
    </div>
  );
}

function MaterialTable({ lines }: { lines: CostLine[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!lines.length) {
    return (
      <p className={base.empty}>
        这个成品还没有配件清单。先去库存模块把物料清单录全，否则这张表是空的。
      </p>
    );
  }

  return (
    <div className={base.panel}>
      <div className={base.panelHead}>
        <span className={base.panelTitle}>物料</span>
      </div>
      <div className={base.tableWrap}>
        <table className={base.table}>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th className={base.num}>用量</th>
              <th className={base.num}>单价</th>
              <th className={base.num}>运费</th>
              <th className={base.num}>小计</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr
                className={line.missing_price ? styles.missingRow : undefined}
                key={`${line.code ?? line.name}-${index}`}
              >
                <td>
                  <span className={base.code}>{line.code}</span>
                </td>
                <td>
                  {line.name}
                  {line.price_source === "reference" ? (
                    <span className={base.tagWarn}>参考价·未入库</span>
                  ) : null}
                  {line.estimated_price ? (
                    <span className={base.tagWarn}>暂估价</span>
                  ) : null}
                </td>
                <td className={base.num}>
                  {fmtQty(line.qty)} {line.unit}
                </td>
                <td className={base.num}>
                  {line.missing_price ? (
                    <span className={styles.missing}>缺价</span>
                  ) : (
                    <>
                      {money(line.unit_price)}
                      {line.crosses_batches ? (
                        <button
                          className={styles.crossBatch}
                          onClick={() =>
                            setExpanded(expanded === index ? null : index)
                          }
                          type="button"
                        >
                          跨 {line.batches.length} 批
                        </button>
                      ) : null}
                    </>
                  )}
                </td>
                <td className={base.num}>{money(line.unit_freight)}</td>
                <td className={base.num}>{money(line.line_material)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {expanded !== null && lines[expanded]?.batches.length ? (
        <div className={styles.breakdown}>
          <p className={base.hint}>
            {lines[expanded].name} 的这个单价是加权出来的，取自这几批：
          </p>
          <ul>
            {lines[expanded].batches.map((batch) => (
              <li key={batch.movement_id + batch.at}>
                {new Date(batch.at).toLocaleDateString("zh-CN")} · 取{" "}
                {fmtQty(batch.qty)} · 单价 {money(batch.unit_price)}
                {batch.extrapolated ? "（库存不足，按最新批次外推）" : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function Total({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className={emphasis ? styles.totalStrong : styles.total}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ProcessPanel({
  processes,
  onChanged,
}: {
  processes: LaborProcess[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [rate, setRate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    if (!name.trim() || !rate.trim()) return;
    setBusy(true);
    try {
      await createProcess({ name: name.trim(), rate: rate.trim() });
      setName("");
      setRate("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新建失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={base.panel}>
      <div className={base.panelHead}>
        <span className={base.panelTitle}>工序库</span>
        <span className={base.muted}>
          工价挂在工序上，涨工资改一次，全部产品下次生产自动生效
        </span>
      </div>
      {error ? <p className={base.error}>{error}</p> : null}
      <div className={base.row}>
        <input
          className={base.input}
          onChange={(event) => setName(event.target.value)}
          placeholder="工序名（组装 / 焊接 / 测试 / 包装）"
          value={name}
        />
        <input
          className={base.inputSm}
          inputMode="decimal"
          onChange={(event) => setRate(event.target.value)}
          placeholder="工价"
          value={rate}
        />
        <button
          className={base.btnPrimary}
          disabled={busy || !name.trim() || !rate.trim()}
          onClick={add}
          type="button"
        >
          新建工序
        </button>
      </div>
      {processes.length ? (
        <div className={base.tableWrap}>
          <table className={base.table}>
            <thead>
              <tr>
                <th>工序</th>
                <th className={base.num}>当前工价</th>
                <th>生效日</th>
                <th className={base.num}>被几个产品用</th>
              </tr>
            </thead>
            <tbody>
              {processes.map((process) => (
                <tr key={process.id}>
                  <td>{process.name}</td>
                  <td className={base.num}>{money(process.rate)}</td>
                  <td>{process.rate_effective_date ?? "—"}</td>
                  <td className={base.num}>{process.used_by_product_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className={base.empty}>还没有工序。</p>
      )}
    </div>
  );
}
