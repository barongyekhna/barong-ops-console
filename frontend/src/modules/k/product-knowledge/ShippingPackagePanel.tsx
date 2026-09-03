"use client";

/**
 * 运费（独立站）+ 包装清单。
 *
 * 从 ProductDetail 抽出的第二簇（2026-09-01）。这两块合成一个面板，
 * 因为它们读的是同一份「刚拉回来的产品详情」，而且都只在 DTC 渠道下有意义。
 *
 * 抽之前顺手纠了一个命名误导：上层那个 state 原来叫 `shippingProduct`，
 * 名字像是「运费专用的产品」，实际上它就是**重新拉取的完整详情**，
 * 事实规格面板也在读它。改叫 `productDetail` 之后，这个面板拿到的是
 * 一份只读快照 + 一个「我改完了，你去重拉」的回调。
 *
 * 两条家规钉在这里：
 * - 包装清单**逐项必须英文**——件数声明按它校验，中文会让校验读不懂。
 * - 运费未分配的产品，P 系列上架前必须解决，所以这里把「未分配」写成人话
 *   而不是留空。
 */

import { LoaderCircle, Plus, RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";

import {
  assignProductShipping,
  getShippingClasses,
  patchProductShipping,
  updateProduct,
} from "./api";
import styles from "./ProductKnowledge.module.css";
import type {
  ProductKnowledgeDetail,
  WShippingClassOption,
} from "./types";

/** 运费类操作失败的统一话术。详情页加载失败也复用它，所以放在这里对外提供。 */
export function shippingOperationError(error: unknown) {
  return `运费操作失败：${error instanceof Error ? error.message : ""}`;
}

/** 下拉的「还没选」态。空串是有意义的值（清除指定），不能拿它当未选。 */
const SHIPPING_SELECTION_UNSET = "__unset__";

type ShippingPackagePanelProps = {
  /** 重新拉取过的完整详情。为 null 表示还在加载。 */
  productDetail: ProductKnowledgeDetail;
  /** 改完之后请上层重拉详情——这个面板不持有产品数据的真相。 */
  onRefreshDetail: (productId: string) => Promise<unknown>;
};

export function ShippingPackagePanel({
  productDetail,
  onRefreshDetail,
}: ShippingPackagePanelProps) {
  const [shippingClasses, setShippingClasses] = useState<
    WShippingClassOption[]
  >([]);
  const [selection, setSelection] = useState(SHIPPING_SELECTION_UNSET);
  const [shippingError, setShippingError] = useState("");
  const [shippingNotice, setShippingNotice] = useState("");
  const [busy, setBusy] = useState<"save" | "assign" | "battery" | null>(null);
  const [packageIncludes, setPackageIncludes] = useState<string[]>([""]);
  const [packageError, setPackageError] = useState("");
  const [packageNotice, setPackageNotice] = useState("");
  const [isSavingPackage, setIsSavingPackage] = useState(false);

  const isDtc = productDetail.channel === "dtc";
  const productId = productDetail.id;

  // 运费类清单只在 DTC 下才有意义，非 DTC 不去打这个接口。
  useEffect(() => {
    if (!isDtc) {
      setShippingClasses([]);
      return;
    }
    let cancelled = false;
    void getShippingClasses()
      .then((items) => {
        if (!cancelled) {
          setShippingClasses(items.filter((item) => item.active));
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setShippingError(shippingOperationError(error));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isDtc, productId]);

  useEffect(() => {
    const items = Array.isArray(productDetail.package_includes_json)
      ? productDetail.package_includes_json.filter(
          (item): item is string => typeof item === "string",
        )
      : [];
    setPackageIncludes(items.length > 0 ? items : [""]);
    setPackageError("");
  }, [productDetail.id, productDetail.package_includes_json]);

  const shippingClassName = productDetail.shipping_class
    ? shippingClasses.find(
        (shippingClass) => shippingClass.slug === productDetail.shipping_class,
      )?.name ?? productDetail.shipping_class
    : null;

  function updatePackageItem(index: number, value: string) {
    setPackageIncludes((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? value : item)),
    );
    setPackageError("");
    setPackageNotice("");
  }

  async function savePackageIncludes() {
    const populated = packageIncludes.map((item) => item.trim()).filter(Boolean);
    if (populated.some((item) => /[\u3400-\u9fff]/u.test(item))) {
      setPackageError("包装清单必须逐项使用英文，不能包含中文。");
      return;
    }
    setIsSavingPackage(true);
    setPackageError("");
    try {
      await updateProduct(productId, {
        package_includes_json: populated.length > 0 ? populated : null,
      });
      await onRefreshDetail(productId);
      setPackageNotice("包装清单已保存 ✓");
    } catch (error) {
      setPackageError(
        error instanceof Error ? error.message : "包装清单保存失败。",
      );
    } finally {
      setIsSavingPackage(false);
    }
  }

  async function saveShippingAssignment() {
    if (selection === SHIPPING_SELECTION_UNSET) {
      return;
    }
    setBusy("save");
    setShippingError("");
    try {
      await patchProductShipping(
        productId,
        selection
          ? { clear_review: true, shipping_class_slug: selection }
          : { clear_review: false, shipping_class_slug: null },
      );
      await onRefreshDetail(productId);
      setSelection(SHIPPING_SELECTION_UNSET);
      setShippingNotice("运费模板已保存 ✓");
    } catch (error) {
      setShippingNotice("");
      setShippingError(shippingOperationError(error));
    } finally {
      setBusy(null);
    }
  }

  async function reassignShipping() {
    setBusy("assign");
    setShippingError("");
    try {
      await assignProductShipping(productId);
      await onRefreshDetail(productId);
    } catch (error) {
      setShippingError(shippingOperationError(error));
    } finally {
      setBusy(null);
    }
  }

  async function setContainsBattery(containsBattery: boolean) {
    setBusy("battery");
    setShippingError("");
    try {
      await patchProductShipping(productId, {
        contains_battery: containsBattery,
      });
      await onRefreshDetail(productId);
    } catch (error) {
      setShippingError(shippingOperationError(error));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {isDtc ? (
        <section
          aria-labelledby="k-shipping"
          className={styles.workflowSection}
        >
          <div className={styles.sellingPointsHeading}>
            <div>
              <h4 id="k-shipping">运费（独立站）</h4>
            </div>
          </div>

          <div className={styles.workflowMetrics}>
            <div>
              <dd>
                {shippingClassName ? (
                  <>
                    {shippingClassName}{" "}
                    <span className={styles.statusBadge}>
                      {productDetail.shipping_assignment?.rule_type
                        ? "规则判定"
                        : "手动指定"}
                    </span>
                  </>
                ) : (
                  "未分配——P 系列上架前必须解决"
                )}
              </dd>
            </div>
            {productDetail.shipping_review_needed ? (
              <div>
                <dd>
                  待复核：
                  {productDetail.shipping_assignment?.review_reason ||
                    "缺少判定依据"}
                </dd>
              </div>
            ) : null}
          </div>

          {productDetail.shipping_assignment?.used_kg != null ? (
            <p className={styles.sellingPointsEmpty}>
              判定重量 {productDetail.shipping_assignment.used_kg} kg
            </p>
          ) : null}

          <div className={styles.workflowStartGrid}>
            <label className={styles.field}>
              <select
                aria-label="选择运费类…"
                disabled={busy !== null}
                onChange={(event) => setSelection(event.target.value)}
                value={selection}
              >
                <option disabled value={SHIPPING_SELECTION_UNSET}>
                  选择运费类…
                </option>
                <option value="">（清除指定）</option>
                {shippingClasses.map((shippingClass) => (
                  <option key={shippingClass.id} value={shippingClass.slug}>
                    {shippingClass.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary-button"
              disabled={busy !== null || selection === SHIPPING_SELECTION_UNSET}
              onClick={() => void saveShippingAssignment()}
              type="button"
            >
              {busy === "save" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <Save aria-hidden="true" size={16} />
              )}
              保存指定
            </button>
            <button
              className="secondary-button"
              disabled={busy !== null}
              onClick={() => void reassignShipping()}
              type="button"
            >
              {busy === "assign" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={16} />
              ) : (
                <RotateCcw aria-hidden="true" size={16} />
              )}
              按规则重判
            </button>
          </div>

          <div className={styles.workflowMetrics}>
            <div>
              <label>
                <input
                  checked={Boolean(productDetail.contains_battery)}
                  disabled={busy !== null}
                  onChange={(event) =>
                    void setContainsBattery(event.target.checked)
                  }
                  type="checkbox"
                />{" "}
                含电池（命中电池规则）
              </label>
            </div>
          </div>

          {shippingError ? (
            <p className={styles.sellingPointsError}>{shippingError}</p>
          ) : null}
          {shippingNotice ? (
            <p className={styles.spSaveNotice} role="status">
              {shippingNotice}
            </p>
          ) : null}
        </section>
      ) : null}

      <section
        aria-labelledby="k-package-includes"
        className={styles.workflowSection}
      >
        <div className={styles.sellingPointsHeading}>
          <div>
            <span className={styles.eyebrow}>套装证据</span>
            <h4 id="k-package-includes">包装清单 (What&apos;s in the box)</h4>
          </div>
          <button
            className="secondary-button"
            onClick={() => setPackageIncludes((current) => [...current, ""])}
            type="button"
          >
            <Plus aria-hidden="true" size={15} />
            添加组件
          </button>
        </div>
        <p className={styles.keywordAiNotice}>
          每行一个已核实的组件，必须用英文；件数声明将严格按此清单校验。
        </p>
        {packageIncludes.map((item, index) => (
          <div className={styles.workflowStartGrid} key={`package-item-${index}`}>
            <label className={styles.field}>
              <span>组件 {index + 1}</span>
              <input
                lang="en"
                onChange={(event) => updatePackageItem(index, event.target.value)}
                placeholder="e.g. 1.5 qt pot"
                value={item}
              />
            </label>
            <button
              className="secondary-button"
              disabled={packageIncludes.length <= 1}
              onClick={() =>
                setPackageIncludes((current) =>
                  current.filter((_, itemIndex) => itemIndex !== index),
                )
              }
              type="button"
            >
              删除
            </button>
          </div>
        ))}
        {packageError ? (
          <p className={styles.sellingPointsError}>{packageError}</p>
        ) : null}
        {packageNotice ? (
          <p className={styles.spSaveNotice} role="status">
            {packageNotice}
          </p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span>留空表示未知，不会自动补齐或猜测组件。</span>
          <button
            className="primary-button"
            disabled={isSavingPackage}
            onClick={() => void savePackageIncludes()}
            type="button"
          >
            {isSavingPackage ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存包装清单
          </button>
        </div>
      </section>
    </>
  );
}
