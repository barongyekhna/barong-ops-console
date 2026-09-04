"use client";

import { LoaderCircle, Plus, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getProduct, updateProductFaq, type ProductFaqItem } from "./api";
import styles from "./ProductKnowledge.module.css";

function formatError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "保存失败，请重试。";
}

/**
 * FAQ 人工编辑面板。
 * page_faq 是唯一数据源：页面可见 FAQ、FAQPage 结构化数据都由它派生。
 * 这里改完 → 名册点「重推」→ 两处自动同步（同一链接原地更新）。
 */
export function FaqEditorPanel({
  productId,
  refreshKey = 0,
}: {
  productId: string;
  /** 上层数据变化(如文案生成完成)时 +1，触发重新拉取。 */
  refreshKey?: number;
}) {
  const [items, setItems] = useState<ProductFaqItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const product = await getProduct(productId);
      const mcj = (
        product as { marketing_copy_json?: { page_faq?: unknown } | null }
      ).marketing_copy_json;
      const raw = Array.isArray(mcj?.page_faq) ? mcj.page_faq : [];
      setItems(
        raw
          .filter(
            (entry): entry is { question?: unknown; answer?: unknown } =>
              Boolean(entry) && typeof entry === "object",
          )
          .map((entry) => ({
            question: typeof entry.question === "string" ? entry.question : "",
            answer: typeof entry.answer === "string" ? entry.answer : "",
          })),
      );
      setDirty(false);
    } catch (loadError) {
      setError(formatError(loadError));
    } finally {
      setLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  function updateItem(index: number, patch: Partial<ProductFaqItem>) {
    setItems((current) =>
      current.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
    setDirty(true);
    setNotice("");
  }

  function removeItem(index: number) {
    setItems((current) => current.filter((_, i) => i !== index));
    setDirty(true);
    setNotice("");
  }

  function addItem() {
    setItems((current) => [...current, { question: "", answer: "" }]);
    setDirty(true);
    setNotice("");
  }

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const cleaned = items
        .map((item) => ({
          question: item.question.trim(),
          answer: item.answer.trim(),
        }))
        .filter((item) => item.question || item.answer);
      const result = await updateProductFaq(productId, cleaned);
      setItems(result.page_faq);
      setDirty(false);
      setNotice(
        result.page_faq.length
          ? `已保存 ${result.page_faq.length} 条。到名册点「重推」即可上站——可见 FAQ 与结构化数据会自动同步。`
          : "已清空 FAQ。重推后页面与结构化数据都不再输出 FAQ（保持一致，不留残留）。",
      );
    } catch (saveError) {
      setError(formatError(saveError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-labelledby="k-faq-editor"
      className={styles.sellingPointsSection}
    >
      <header className={styles.sellingPointsHeader}>
        <div>
          <h4 id="k-faq-editor">FAQ · 人工编辑（上架前后均可）</h4>
          <p className={styles.sellingPointsHint}>
            英文问句（以 ? 结尾）。保存后到名册点「重推」——页面可见 FAQ 与
            FAQPage 结构化数据永远同一份，绝不打架。
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="secondary-button"
            disabled={loading || saving}
            onClick={addItem}
            type="button"
          >
            <Plus aria-hidden="true" size={15} />
            新增
          </button>
          <button
            className="secondary-button"
            disabled={loading || saving || !dirty}
            onClick={() => void save()}
            type="button"
          >
            {saving ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <Save aria-hidden="true" size={15} />
            )}
            保存
          </button>
        </div>
      </header>
      {loading ? (
        <p className={styles.sellingPointsHint}>加载中…</p>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.length === 0 ? (
            <p className={styles.sellingPointsHint}>
              暂无 FAQ。点「新增」手写，或在文案生成阶段由研究簇自动产出。
            </p>
          ) : null}
          {items.map((item, index) => (
            <div
              key={index}
              style={{
                border: "1px solid var(--color-line)",
                borderRadius: 10,
                display: "grid",
                gap: 8,
                padding: 12,
              }}
            >
              <input
                aria-label={`FAQ 问题 ${index + 1}`}
                onChange={(event) =>
                  updateItem(index, { question: event.target.value })
                }
                placeholder="Question (English, ends with ?)"
                style={{ fontWeight: 600, width: "100%" }}
                value={item.question}
              />
              <textarea
                aria-label={`FAQ 答案 ${index + 1}`}
                onChange={(event) =>
                  updateItem(index, { answer: event.target.value })
                }
                placeholder="Answer (English; advice first, no spec-number recitation)"
                rows={3}
                style={{ resize: "vertical", width: "100%" }}
                value={item.answer}
              />
              <div>
                <button
                  className="secondary-button"
                  disabled={saving}
                  onClick={() => removeItem(index)}
                  type="button"
                >
                  <Trash2 aria-hidden="true" size={14} />
                  删除此条
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {notice ? <p className={styles.sellingPointsHint}>{notice}</p> : null}
      {error ? (
        <p className={styles.sellingPointsHint} style={{ color: "var(--color-error)" }}>
          {error}
        </p>
      ) : null}
    </section>
  );
}
