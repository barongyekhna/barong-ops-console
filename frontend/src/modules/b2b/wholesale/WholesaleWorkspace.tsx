"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./Wholesale.module.css";
import {
  type CategoryReadiness,
  type WholesaleItem,
  type WholesaleItemList,
  type WholesaleStatus,
  batchPatchWholesaleItems,
  exportLineSheet,
  getCategoryReadiness,
  getWholesaleItems,
} from "./api";

type DraftRow = {
  wholesale_price: string;
  case_pack: string;
  moq_units: string;
  lead_time_days: string;
};

type Drafts = Record<string, DraftRow>;

const EMPTY_DRAFT: DraftRow = {
  wholesale_price: "",
  case_pack: "",
  moq_units: "",
  lead_time_days: "",
};

function draftFromItem(item: WholesaleItem): DraftRow {
  return {
    wholesale_price: item.wholesale_price ?? "",
    case_pack: item.case_pack?.toString() ?? "",
    moq_units: item.moq_units?.toString() ?? "",
    lead_time_days: item.lead_time_days?.toString() ?? "",
  };
}

function money(value: string | null): string {
  if (!value) return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : value;
}

/** 毛利率:店家一眼要看的就是这个数,决定他进不进货。 */
function marginPercent(item: WholesaleItem, draft?: DraftRow): number | null {
  const msrp = Number(item.msrp ?? "");
  const wholesale = Number(draft?.wholesale_price || item.wholesale_price || "");
  if (!Number.isFinite(msrp) || !Number.isFinite(wholesale) || msrp <= 0) {
    return null;
  }
  return ((msrp - wholesale) / msrp) * 100;
}

function categoryLabel(path: string[]): string {
  return path.length ? path.join(" › ") : "（未分类）";
}

export function WholesaleWorkspace() {
  const [data, setData] = useState<WholesaleItemList | null>(null);
  const [readiness, setReadiness] = useState<CategoryReadiness[]>([]);
  const [minReady, setMinReady] = useState(30);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [statusFilter, setStatusFilter] = useState<WholesaleStatus | "">("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [items, cats] = await Promise.all([
        getWholesaleItems({ status: statusFilter, search }),
        getCategoryReadiness(),
      ]);
      setData(items);
      setReadiness(cats.categories);
      setMinReady(cats.min_ready_items);
      setDrafts({});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const items = data?.items ?? [];

  const updateDraft = (id: string, field: keyof DraftRow, value: string) => {
    setDrafts((current) => {
      const base =
        current[id] ??
        draftFromItem(items.find((item) => item.id === id) ?? ({} as WholesaleItem));
      return { ...current, [id]: { ...EMPTY_DRAFT, ...base, [field]: value } };
    });
  };

  const dirtyIds = useMemo(() => {
    return Object.keys(drafts).filter((id) => {
      const item = items.find((candidate) => candidate.id === id);
      if (!item) return false;
      const original = draftFromItem(item);
      const draft = drafts[id];
      return (
        draft.wholesale_price !== original.wholesale_price ||
        draft.case_pack !== original.case_pack ||
        draft.moq_units !== original.moq_units ||
        draft.lead_time_days !== original.lead_time_days
      );
    });
  }, [drafts, items]);

  const save = async () => {
    if (!dirtyIds.length) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload = dirtyIds.map((id) => {
        const draft = drafts[id];
        const entry: Record<string, unknown> = { item_id: id };
        if (draft.wholesale_price.trim()) {
          entry.wholesale_price = Number(draft.wholesale_price);
        }
        if (draft.case_pack.trim()) entry.case_pack = Number(draft.case_pack);
        if (draft.moq_units.trim()) entry.moq_units = Number(draft.moq_units);
        if (draft.lead_time_days.trim()) {
          entry.lead_time_days = Number(draft.lead_time_days);
        }
        return entry as never;
      });
      await batchPatchWholesaleItems(payload);
      setNotice(`已保存 ${dirtyIds.length} 个产品的批发信息。`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  const doExport = async (fmt: "pdf" | "csv", prefix: string[] | null) => {
    setExporting(true);
    setError(null);
    setNotice(null);
    try {
      const { blob, filename } = await exportLineSheet({
        fmt,
        category_prefix: prefix,
        edition_label: new Date().toISOString().slice(0, 7),
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice(`已导出 ${filename}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className={styles.workspace}>
      <section className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>待填批发信息</span>
          <strong className={styles.summaryValuePending}>
            {data?.pending_count ?? "—"}
          </strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>可出图册</span>
          <strong className={styles.summaryValueReady}>
            {data?.ready_count ?? "—"}
          </strong>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>待复核（零售价变了）</span>
          <strong className={styles.summaryValueReview}>
            {data?.needs_review_count ?? "—"}
          </strong>
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>类目成熟度</h2>
          <p className={styles.hint}>
            一个类目里可出图册的产品满 {minReady} 个才解锁挖客户——目录太薄，
            第一印象砸了就回不来。
          </p>
        </header>
        {readiness.length === 0 ? (
          <p className={styles.empty}>还没有产品流入批发目录。</p>
        ) : (
          <ul className={styles.catList}>
            {readiness.map((entry) => (
              <li
                className={styles.catRow}
                key={entry.category_path.join("/") || "uncategorised"}
              >
                <span className={styles.catName}>
                  {categoryLabel(entry.category_path)}
                </span>
                <span className={styles.catBarWrap}>
                  <span
                    className={styles.catBar}
                    data-unlocked={entry.prospecting_unlocked}
                    style={{
                      width: `${Math.min(
                        100,
                        (entry.ready_items / minReady) * 100,
                      )}%`,
                    }}
                  />
                </span>
                <span className={styles.catCount}>
                  {entry.ready_items} / {minReady}
                </span>
                {entry.prospecting_unlocked ? (
                  <span className={styles.badgeOk}>可挖客户</span>
                ) : (
                  <span className={styles.badgeLocked}>
                    还差 {entry.shortfall} 个
                  </span>
                )}
                <button
                  className={styles.exportSmall}
                  disabled={exporting || !entry.ready_items}
                  onClick={() => void doExport("pdf", entry.category_path)}
                  type="button"
                >
                  导出这个类目
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <h2>批发信息填写</h2>
          <div className={styles.toolbar}>
            <input
              className={styles.searchInput}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜 SKU 或产品名"
              value={search}
            />
            <select
              className={styles.filterSelect}
              onChange={(event) =>
                setStatusFilter(event.target.value as WholesaleStatus | "")
              }
              value={statusFilter}
            >
              <option value="">全部</option>
              <option value="pending">待填</option>
              <option value="ready">可出图册</option>
            </select>
            <button
              className={styles.primaryButton}
              disabled={saving || !dirtyIds.length}
              onClick={() => void save()}
              type="button"
            >
              {saving ? "保存中…" : `保存（${dirtyIds.length}）`}
            </button>
            <button
              className={styles.ghostButton}
              disabled={exporting || !data?.ready_count}
              onClick={() => void doExport("pdf", null)}
              type="button"
            >
              导出全部 PDF
            </button>
            <button
              className={styles.ghostButton}
              disabled={exporting || !data?.ready_count}
              onClick={() => void doExport("csv", null)}
              type="button"
            >
              导出 CSV
            </button>
          </div>
        </header>

        {error ? <p className={styles.error}>{error}</p> : null}
        {notice ? <p className={styles.notice}>{notice}</p> : null}

        {loading ? (
          <p className={styles.empty}>加载中…</p>
        ) : items.length === 0 ? (
          <p className={styles.empty}>
            没有产品。产品在 P 系列上架成功后会自动流入这里。
          </p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>产品</th>
                  <th>零售价</th>
                  <th>批发价</th>
                  <th>毛利率</th>
                  <th>箱规</th>
                  <th>起订量</th>
                  <th>交期(天)</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const draft = drafts[item.id] ?? draftFromItem(item);
                  const margin = marginPercent(item, draft);
                  const dirty = dirtyIds.includes(item.id);
                  return (
                    <tr data-dirty={dirty} key={item.id}>
                      <td>
                        <div className={styles.productCell}>
                          <strong className={styles.sku}>{item.sku}</strong>
                          <span className={styles.productName}>
                            {item.product_name}
                          </span>
                          <span className={styles.catPath}>
                            {categoryLabel(item.category_path)}
                          </span>
                          {item.needs_review ? (
                            <span className={styles.reviewFlag}>
                              ⚠ {item.review_reason ?? "零售价已变，请复核"}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className={styles.msrpCell}>{money(item.msrp)}</td>
                      <td>
                        <input
                          className={styles.numInput}
                          inputMode="decimal"
                          onChange={(event) =>
                            updateDraft(
                              item.id,
                              "wholesale_price",
                              event.target.value,
                            )
                          }
                          placeholder="必填"
                          value={draft.wholesale_price}
                        />
                      </td>
                      <td className={styles.marginCell}>
                        {margin === null ? (
                          "—"
                        ) : (
                          <span data-thin={margin < 40}>
                            {margin.toFixed(0)}%
                          </span>
                        )}
                      </td>
                      <td>
                        <input
                          className={styles.numInputSmall}
                          inputMode="numeric"
                          onChange={(event) =>
                            updateDraft(item.id, "case_pack", event.target.value)
                          }
                          placeholder="必填"
                          value={draft.case_pack}
                        />
                      </td>
                      <td>
                        <input
                          className={styles.numInputSmall}
                          inputMode="numeric"
                          onChange={(event) =>
                            updateDraft(item.id, "moq_units", event.target.value)
                          }
                          placeholder="必填"
                          value={draft.moq_units}
                        />
                      </td>
                      <td>
                        <input
                          className={styles.numInputSmall}
                          inputMode="numeric"
                          onChange={(event) =>
                            updateDraft(
                              item.id,
                              "lead_time_days",
                              event.target.value,
                            )
                          }
                          placeholder="必填"
                          value={draft.lead_time_days}
                        />
                      </td>
                      <td>
                        {item.status === "ready" ? (
                          <span className={styles.badgeOk}>可出图册</span>
                        ) : (
                          <span className={styles.badgePending}>待填</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
