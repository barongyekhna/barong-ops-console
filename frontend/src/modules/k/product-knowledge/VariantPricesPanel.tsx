"use client";

/**
 * 变体价格核对。
 *
 * 从 ProductDetail 抽出来的第一簇（2026-09-01）。抽的理由不是「文件太长」，
 * 是这四个 state 只服务这一张表、只被这一个 handler 读写，混在那 57 个
 * useState 里改任何一处都得先确认它没被别处用到。
 *
 * 家规：多变体产品的价格**全部按变体走**，父级价格留空。所以这里不允许留空——
 * 留空的变体上架后在 Woo 里就是没有价格的商品。
 */

import { CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { getProduct, updateVariantPrices } from "./api";
import { formatVariantDisplayName } from "./display";
import type { ProductKnowledgeDetail } from "./types";
import styles from "./ProductKnowledge.module.css";

type VariantPricesPanelProps = {
  product: ProductKnowledgeDetail;
  /** 保存成功后把刷新过的产品交回上层，避免上层拿着旧价格继续渲染。 */
  onProductPatched?: (product: ProductKnowledgeDetail) => void;
};

export function VariantPricesPanel({
  product,
  onProductPatched,
}: VariantPricesPanelProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  async function save() {
    const variants = product.variants ?? [];
    const items: { variant_id: string; price_override: number }[] = [];
    for (const variant of variants) {
      const draft = drafts[variant.id];
      if (draft === undefined) {
        continue;
      }
      const trimmed = draft.trim();
      if (!trimmed) {
        setError("变体价格不能留空——多变体产品每个变体都必须有价。");
        return;
      }
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed) || parsed < 0) {
        setError(
          `「${formatVariantDisplayName(variant)}」的价格不是有效数字。`,
        );
        return;
      }
      const current = variant.price_override;
      if (current !== null && Math.abs(current - parsed) < 0.005) {
        continue;
      }
      items.push({ price_override: parsed, variant_id: variant.id });
    }
    if (!items.length) {
      setError("");
      setStatus("没有改动。");
      return;
    }
    setIsSaving(true);
    setError("");
    setStatus("");
    try {
      await updateVariantPrices(product.id, items);
      const refreshed = await getProduct(product.id);
      onProductPatched?.(refreshed);
      setDrafts({});
      setStatus(`已保存 ${items.length} 个变体的价格。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败，请重试。");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section
      aria-labelledby="k-variant-prices"
      className={styles.workflowSection}
    >
      <div className={styles.sellingPointsHeading}>
        <div>
          <h4 id="k-variant-prices">变体价格核对</h4>
          <p className={styles.sectionHint}>
            {product.product_type === "variable_product"
              ? "多变体产品的价格全部按变体走（父级价格留空）。逐行核对，改完点保存。"
              : "核对该产品的定价，改完点保存。"}
          </p>
        </div>
      </div>

      <div className={styles.variantPriceTableWrap}>
        <table className={styles.variantPriceTable}>
          <thead>
            <tr>
              <th scope="col">变体</th>
              <th scope="col">SKU</th>
              {/* 站点单一币种结算,读取接口也不返 price_currency */}
              <th scope="col">价格（USD）</th>
            </tr>
          </thead>
          <tbody>
            {(product.variants ?? []).map((variant) => {
              const draft = drafts[variant.id];
              const stored =
                variant.price_override === null
                  ? ""
                  : String(variant.price_override);
              const value = draft === undefined ? stored : draft;
              const missing = value.trim() === "";
              const changed = draft !== undefined && draft.trim() !== stored;
              return (
                <tr key={variant.id}>
                  <td>
                    <strong>{formatVariantDisplayName(variant)}</strong>
                  </td>
                  <td className={styles.variantPriceSku}>
                    {variant.variant_sku}
                  </td>
                  <td>
                    <div className={styles.variantPriceCell}>
                      <input
                        aria-label={`${formatVariantDisplayName(variant)} 的价格`}
                        data-missing={missing}
                        disabled={isSaving}
                        inputMode="decimal"
                        min={0}
                        onChange={(event) => {
                          setStatus("");
                          setDrafts((previous) => ({
                            ...previous,
                            [variant.id]: event.target.value,
                          }));
                        }}
                        placeholder="未设置"
                        step={0.01}
                        type="number"
                        value={value}
                      />
                      {missing ? (
                        <span
                          className={styles.variantPriceFlag}
                          data-tone="bad"
                        >
                          未设置
                        </span>
                      ) : null}
                      {changed ? (
                        <span
                          className={styles.variantPriceFlag}
                          data-tone="changed"
                        >
                          待保存
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {error ? (
        <p className={styles.sellingPointsError} role="alert">
          {error}
        </p>
      ) : null}

      <div className={styles.variantPriceActions}>
        {status ? (
          <span className={styles.variantPriceStatus}>{status}</span>
        ) : null}
        <button
          className="secondary-button"
          disabled={isSaving || Object.keys(drafts).length === 0}
          onClick={() => void save()}
          type="button"
        >
          <CheckCircle2 aria-hidden="true" size={15} />
          {isSaving ? "保存中…" : "保存价格"}
        </button>
      </div>
    </section>
  );
}
