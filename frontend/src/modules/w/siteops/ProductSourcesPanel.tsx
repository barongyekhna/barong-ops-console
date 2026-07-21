"use client";

import {
  Fragment,
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  deleteProductSource,
  getProductSources,
  isHttpProductSourceUrl,
  normalizeProductSourceSku,
  type ProductSource,
  type ProductSourcePayload,
  type ProductSourcesResponse,
  upsertProductSource,
} from "./api";
import styles from "./ShippingDeck.module.css";

type SourceEditorProps = {
  compact?: boolean;
  disabled?: boolean;
  initialSku?: string;
  onCancel: () => void;
  onSaved: (source: ProductSource) => void | Promise<void>;
  skuReadOnly?: boolean;
  source?: ProductSource | null;
  submitLabel?: string;
};

type SourceDraft = {
  sku: string;
  sourceUrl: string;
  supplierName: string;
  unitCost: string;
  currency: string;
  moq: string;
  notes: string;
};

const EMPTY_RESPONSE: ProductSourcesResponse = {
  items: [],
  page: 1,
  page_size: 50,
  total: 0,
  pages: 1,
};

function sourceErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "货源操作失败";
}

function toDraft(
  source: ProductSource | null | undefined,
  initialSku: string,
): SourceDraft {
  return {
    sku: source?.sku ?? normalizeProductSourceSku(initialSku),
    sourceUrl: source?.source_url ?? "",
    supplierName: source?.supplier_name ?? "",
    unitCost:
      source?.unit_cost === null || source?.unit_cost === undefined
        ? ""
        : String(source.unit_cost),
    currency: source?.currency ?? "CNY",
    moq:
      source?.moq === null || source?.moq === undefined
        ? ""
        : String(source.moq),
    notes: source?.notes ?? "",
  };
}

function parseOptionalUnitCost(value: string) {
  const normalized = value.trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error("进货价必须是大于等于 0 的数字");
  }
  return parsed;
}

function parseOptionalMoq(value: string) {
  const normalized = value.trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error("起订量必须是大于等于 1 的整数");
  }
  return parsed;
}

function buildPayload(draft: SourceDraft): ProductSourcePayload {
  const sourceUrl = draft.sourceUrl.trim();
  if (!isHttpProductSourceUrl(sourceUrl)) {
    throw new Error("1688 链接必须是完整的 http/https 地址");
  }
  const currency = draft.currency.trim().toUpperCase();
  if (!currency) throw new Error("币种不能为空");
  return {
    source_url: sourceUrl,
    supplier_name: draft.supplierName.trim() || null,
    unit_cost: parseOptionalUnitCost(draft.unitCost),
    currency,
    moq: parseOptionalMoq(draft.moq),
    notes: draft.notes.trim() || null,
  };
}

export function ProductSourceEditor({
  compact = false,
  disabled = false,
  initialSku = "",
  onCancel,
  onSaved,
  skuReadOnly = false,
  source = null,
  submitLabel = "保存货源",
}: SourceEditorProps) {
  const [draft, setDraft] = useState<SourceDraft>(() =>
    toDraft(source, initialSku),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const sku = normalizeProductSourceSku(draft.sku);
      if (!sku) {
        setError("SKU 不能为空");
        return;
      }
      setSaving(true);
      setError(null);
      try {
        const saved = await upsertProductSource(sku, buildPayload(draft));
        await onSaved(saved);
      } catch (saveError) {
        setError(sourceErrorMessage(saveError));
      } finally {
        setSaving(false);
      }
    },
    [draft, onSaved],
  );

  const editorDisabled = disabled || saving;

  return (
    <form
      className={styles.sourceEditor}
      data-compact={compact ? "true" : "false"}
      onSubmit={(event) => void handleSubmit(event)}
    >
      <label className={styles.sourceField}>
        <span>SKU</span>
        <input
          autoComplete="off"
          className={styles.formInput}
          disabled={editorDisabled}
          maxLength={64}
          onChange={(event) =>
            setDraft((current) => ({ ...current, sku: event.target.value }))
          }
          readOnly={skuReadOnly}
          required
          value={draft.sku}
        />
      </label>
      <label className={`${styles.sourceField} ${styles.sourceUrlField}`}>
        <span>1688 商品链接</span>
        <input
          autoComplete="url"
          className={styles.formInput}
          disabled={editorDisabled}
          maxLength={1000}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              sourceUrl: event.target.value,
            }))
          }
          placeholder="https://detail.1688.com/offer/…"
          required
          type="url"
          value={draft.sourceUrl}
        />
      </label>
      <label className={styles.sourceField}>
        <span>供应商</span>
        <input
          className={styles.formInput}
          disabled={editorDisabled}
          maxLength={200}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              supplierName: event.target.value,
            }))
          }
          placeholder="可选"
          value={draft.supplierName}
        />
      </label>
      <label className={styles.sourceField}>
        <span>进货价</span>
        <input
          className={styles.formInput}
          disabled={editorDisabled}
          inputMode="decimal"
          min="0"
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              unitCost: event.target.value,
            }))
          }
          placeholder="可选"
          step="0.01"
          type="number"
          value={draft.unitCost}
        />
      </label>
      <label className={styles.sourceField}>
        <span>币种</span>
        <input
          className={styles.formInput}
          disabled={editorDisabled}
          maxLength={8}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              currency: event.target.value,
            }))
          }
          required
          value={draft.currency}
        />
      </label>
      <label className={styles.sourceField}>
        <span>起订量</span>
        <input
          className={styles.formInput}
          disabled={editorDisabled}
          inputMode="numeric"
          min="1"
          onChange={(event) =>
            setDraft((current) => ({ ...current, moq: event.target.value }))
          }
          placeholder="可选"
          step="1"
          type="number"
          value={draft.moq}
        />
      </label>
      <label className={`${styles.sourceField} ${styles.sourceNotesField}`}>
        <span>备注</span>
        <textarea
          className={styles.formInput}
          disabled={editorDisabled}
          onChange={(event) =>
            setDraft((current) => ({ ...current, notes: event.target.value }))
          }
          placeholder="如：要选蓝色款 / 找王经理"
          rows={compact ? 2 : 3}
          value={draft.notes}
        />
      </label>
      <div className={styles.sourceEditorActions}>
        <button
          className="primary-button"
          disabled={editorDisabled}
          type="submit"
        >
          {saving ? "保存中…" : submitLabel}
        </button>
        <button
          className="secondary-button"
          disabled={editorDisabled}
          onClick={onCancel}
          type="button"
        >
          取消
        </button>
        {error ? (
          <span className={styles.sourceFormError} role="alert">
            {error}
          </span>
        ) : null}
      </div>
    </form>
  );
}

type ProductSourcesPanelProps = {
  onSourceDeleted?: (sku: string) => void;
  onSourceSaved?: (source: ProductSource) => void;
  onTotalChange?: (total: number) => void;
};

function formatCost(source: ProductSource) {
  if (source.unit_cost === null) return "—";
  return `${source.currency || "CNY"} ${source.unit_cost}`;
}

export function ProductSourcesPanel({
  onSourceDeleted,
  onSourceSaved,
  onTotalChange,
}: ProductSourcesPanelProps) {
  const [response, setResponse] =
    useState<ProductSourcesResponse>(EMPTY_RESPONSE);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingSku, setEditingSku] = useState<string | null>(null);
  const [deletingSku, setDeletingSku] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const loadSources = useCallback(
    async (nextQuery: string, nextPage: number) => {
      requestSequence.current += 1;
      const requestId = requestSequence.current;
      setLoading(true);
      setLoadError(null);
      try {
        const data = await getProductSources(nextQuery, nextPage);
        if (requestId !== requestSequence.current) return;
        setResponse(data);
        onTotalChange?.(data.total);
      } catch (error) {
        if (requestId === requestSequence.current) {
          setLoadError(sourceErrorMessage(error));
        }
      } finally {
        if (requestId === requestSequence.current) setLoading(false);
      }
    },
    [onTotalChange],
  );

  useEffect(() => {
    void loadSources(query, page);
    return () => {
      requestSequence.current += 1;
    };
  }, [loadSources, page, query]);

  const handleSearch = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const nextQuery = searchDraft.trim();
      setCreating(false);
      setEditingSku(null);
      if (query === nextQuery && page === 1) {
        void loadSources(nextQuery, 1);
        return;
      }
      setQuery(nextQuery);
      setPage(1);
    },
    [loadSources, page, query, searchDraft],
  );

  const handleCreated = useCallback(
    async (source: ProductSource) => {
      onSourceSaved?.(source);
      setCreating(false);
      setSearchDraft("");
      if (query || page !== 1) {
        setQuery("");
        setPage(1);
      } else {
        await loadSources("", 1);
      }
    },
    [loadSources, onSourceSaved, page, query],
  );

  const handleEdited = useCallback(
    async (source: ProductSource) => {
      onSourceSaved?.(source);
      setEditingSku(null);
      await loadSources(query, page);
    },
    [loadSources, onSourceSaved, page, query],
  );

  const handleDelete = useCallback(
    async (source: ProductSource) => {
      if (
        !window.confirm(
          `确认删除 ${source.sku} 的主货源？订单会重新显示为“补货源”。`,
        )
      ) {
        return;
      }
      setDeletingSku(source.sku);
      setLoadError(null);
      try {
        await deleteProductSource(source.sku);
        onSourceDeleted?.(source.sku);
        setEditingSku(null);
        if (response.items.length === 1 && page > 1) {
          setPage((current) => current - 1);
        } else {
          await loadSources(query, page);
        }
      } catch (error) {
        setLoadError(sourceErrorMessage(error));
      } finally {
        setDeletingSku(null);
      }
    },
    [loadSources, onSourceDeleted, page, query, response.items.length],
  );

  const pageCount = Math.max(
    1,
    response.pages ??
      Math.ceil(response.total / Math.max(response.page_size, 1)),
  );

  return (
    <section className={styles.panel} aria-label="货源库">
      <div className={styles.panelHead}>
        <span className={styles.panelTitle}>货源库 · SKU → 1688 主货源</span>
        <button
          className="primary-button"
          disabled={creating || deletingSku !== null}
          onClick={() => {
            setEditingSku(null);
            setCreating(true);
          }}
          type="button"
        >
          新增货源
        </button>
      </div>
      <p className={styles.mutedLine}>
        一件商品只保留一个主货源；这里负责快速找到采购页，不会自动下单。
      </p>
      <form className={styles.sourceSearch} onSubmit={handleSearch}>
        <input
          aria-label="搜索货源"
          className={styles.formInput}
          onChange={(event) => setSearchDraft(event.target.value)}
          placeholder="搜索 SKU 或供应商"
          value={searchDraft}
        />
        <button className="secondary-button" disabled={loading} type="submit">
          搜索
        </button>
        <button
          className="secondary-button"
          disabled={loading}
          onClick={() => void loadSources(query, page)}
          type="button"
        >
          刷新
        </button>
      </form>

      {creating ? (
        <div className={styles.sourceEditorWrap}>
          <ProductSourceEditor
            onCancel={() => setCreating(false)}
            onSaved={handleCreated}
            submitLabel="新增货源"
          />
        </div>
      ) : null}

      {loadError ? (
        <p className={styles.sourcePanelError} role="alert">
          {loadError}
        </p>
      ) : null}

      {loading ? (
        <div className={styles.state}>正在加载货源库…</div>
      ) : response.items.length === 0 ? (
        <div className={styles.emptyHint}>
          {query ? "没有匹配的货源。" : "还没有货源，先新增一条。"}
        </div>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>SKU</th>
                <th>供应商</th>
                <th>进货价</th>
                <th>起订量</th>
                <th>链接</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {response.items.map((source) => {
                const editing = editingSku === source.sku;
                const deleting = deletingSku === source.sku;
                return (
                  <Fragment key={source.id}>
                    <tr>
                      <td className={styles.sourceSku}>{source.sku}</td>
                      <td>{source.supplier_name ?? "—"}</td>
                      <td>{formatCost(source)}</td>
                      <td>{source.moq ?? "—"}</td>
                      <td>
                        <a
                          className={styles.sourceTextLink}
                          href={source.source_url}
                          rel="noopener noreferrer"
                          target="_blank"
                          title={source.source_url}
                        >
                          打开 ↗
                        </a>
                      </td>
                      <td className={styles.sourceNotes}>{source.notes ?? "—"}</td>
                      <td>
                        <span className={styles.actionRow}>
                          <button
                            className="secondary-button"
                            disabled={deletingSku !== null}
                            onClick={() => {
                              setCreating(false);
                              setEditingSku(editing ? null : source.sku);
                            }}
                            type="button"
                          >
                            {editing ? "收起" : "编辑"}
                          </button>
                          <button
                            className="secondary-button"
                            disabled={deletingSku !== null}
                            onClick={() => void handleDelete(source)}
                            type="button"
                          >
                            {deleting ? "删除中…" : "删除"}
                          </button>
                        </span>
                      </td>
                    </tr>
                    {editing ? (
                      <tr>
                        <td colSpan={7}>
                          <ProductSourceEditor
                            onCancel={() => setEditingSku(null)}
                            onSaved={handleEdited}
                            skuReadOnly
                            source={source}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className={styles.sourcePagination}>
        <span>
          共 {response.total} 条 · 第 {response.page} / {pageCount} 页
        </span>
        <span className={styles.actionRow}>
          <button
            className="secondary-button"
            disabled={loading || page <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            type="button"
          >
            上一页
          </button>
          <button
            className="secondary-button"
            disabled={loading || page >= pageCount}
            onClick={() => setPage((current) => current + 1)}
            type="button"
          >
            下一页
          </button>
        </span>
      </div>
    </section>
  );
}
