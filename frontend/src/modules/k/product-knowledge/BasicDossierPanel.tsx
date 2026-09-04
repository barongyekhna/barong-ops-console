"use client";

/**
 * 基础档案：建好之后也能改「类型与变体」「尺寸重量」「参考图链接」。
 *
 * 背景（2026-09-04）：这三样以前只在「新建产品」表单里。F→K 搬运绕过表单
 * 直接落库（单产品 + 一条 default 变体 + 一张 1688 参考图），落库之后档案页
 * 没有任何入口能补；手工建的产品同样改不了。
 *
 * 三个子块各自独立保存、独立报错。校验与装配复用建品表单搬出来的
 * form-helpers（同一套单位换算、同一套变体规则），不另起炉灶。
 *
 * 约定（同 ShippingPackagePanel）：本面板不持有产品真相，保存后把服务端
 * 回来的产品交给上层（onProductPatched）并请上层重拉详情（onRefreshDetail）。
 */

import { ImagePlus, LoaderCircle, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  addProductReferenceImages,
  mediaAssetThumbnailUrl,
  syncProductVariants,
  updateProduct,
} from "./api";
import { formatVariantAttributes, mediaVariantDisplayName } from "./display";
import {
  ACTIVE_FORM_LOCALE,
  attributePlaceholder,
  buildVariantPayloads,
  dimensionsFormFromJson,
  dimensionsUnitForMarket,
  emptyVariantInput,
  hasDuplicateVariantAttributeTypes,
  normalizeDimensionsInput,
  normalizeWeightInput,
  PRODUCT_FORM_LABELS,
  TARGET_MARKETS,
  targetMarketForCode,
  VARIANT_ATTRIBUTE_TYPES,
  variantAttributeTypeLabel,
  variantFormFromRead,
  weightFormFromJson,
  weightUnitForMarket,
  type VariantDossierRow,
} from "./form-helpers";
import dossierStyles from "./BasicDossierPanel.module.css";
import styles from "./ProductKnowledge.module.css";
import type {
  KMediaAsset,
  ProductDimensionsInput,
  ProductKnowledgeDetail,
  ProductVariantAttributeType,
  ProductWeightInput,
  ReferenceImageOutcome,
} from "./types";

type ProductTypeValue = "simple_product" | "variable_product";

type BasicDossierPanelProps = {
  productDetail: ProductKnowledgeDetail;
  mediaAssets: KMediaAsset[];
  /** 保存成功后把服务端回来的产品交回上层，避免上层拿旧数据继续渲染。 */
  onProductPatched?: (product: ProductKnowledgeDetail) => void;
  /** 请上层重拉详情（运费、规格等面板都读它）。 */
  onRefreshDetail: (productId: string) => Promise<unknown>;
  /** 媒体列表在上层（ProductList.loadWorkflowRuntime 一并重拉媒体）。 */
  onRefreshWorkflow?: () => void;
  onDeleteMedia?: (assetId: string) => Promise<void> | void;
};

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function productTypeOf(value: string | null | undefined): ProductTypeValue {
  return value === "variable_product" ? "variable_product" : "simple_product";
}

export function BasicDossierPanel({
  productDetail,
  mediaAssets,
  onProductPatched,
  onRefreshDetail,
  onRefreshWorkflow,
  onDeleteMedia,
}: BasicDossierPanelProps) {
  const labels = PRODUCT_FORM_LABELS[ACTIVE_FORM_LOCALE];
  const market =
    targetMarketForCode(productDetail.target_market ?? "US") ?? TARGET_MARKETS[0];
  const units = {
    dimensions: dimensionsUnitForMarket(market),
    weight: weightUnitForMarket(market),
  };

  // ---- 尺寸与重量 ----
  const [dimensions, setDimensions] = useState<ProductDimensionsInput>(() =>
    dimensionsFormFromJson(productDetail.dimensions_json, units.dimensions),
  );
  const [weight, setWeight] = useState<ProductWeightInput>(() =>
    weightFormFromJson(productDetail.weight_json, units.weight),
  );
  const [packageDimensions, setPackageDimensions] = useState<ProductDimensionsInput>(
    () => dimensionsFormFromJson(productDetail.package_dimensions_json, units.dimensions),
  );
  const [packageWeight, setPackageWeight] = useState<ProductWeightInput>(() =>
    weightFormFromJson(productDetail.package_weight_json, units.weight),
  );
  const [physicalBusy, setPhysicalBusy] = useState(false);
  const [physicalError, setPhysicalError] = useState("");
  const [physicalNotice, setPhysicalNotice] = useState("");

  // ---- 类型与变体 ----
  const [productType, setProductType] = useState<ProductTypeValue>(() =>
    productTypeOf(productDetail.product_type),
  );
  const [variants, setVariants] = useState<VariantDossierRow[]>(() =>
    (productDetail.variants ?? []).map((variant) => variantFormFromRead(variant, units)),
  );
  const [variantsBusy, setVariantsBusy] = useState(false);
  const [variantsError, setVariantsError] = useState("");
  const [variantsNotice, setVariantsNotice] = useState("");
  const [variantReferenceOutcomes, setVariantReferenceOutcomes] = useState<
    ReferenceImageOutcome[]
  >([]);

  // ---- 参考图链接 ----
  const [referenceUrls, setReferenceUrls] = useState<string[]>([""]);
  const [referenceTarget, setReferenceTarget] = useState("");
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [referenceError, setReferenceError] = useState("");
  const [referenceOutcomes, setReferenceOutcomes] = useState<ReferenceImageOutcome[]>([]);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);

  const savedProductType = productTypeOf(productDetail.product_type);
  const referenceAssets = mediaAssets.filter(
    (asset) => asset.asset_role === "reference" && asset.status !== "removed",
  );

  // ---------------------------------------------------------------- 尺寸与重量
  async function savePhysical() {
    const parsedDimensions = normalizeDimensionsInput(dimensions, market, labels);
    if (!parsedDimensions.ok) {
      setPhysicalError(`产品尺寸：${parsedDimensions.message}`);
      return;
    }
    const parsedWeight = normalizeWeightInput(weight, market, labels);
    if (!parsedWeight.ok) {
      setPhysicalError(`产品重量：${parsedWeight.message}`);
      return;
    }
    const parsedPackageDimensions = normalizeDimensionsInput(
      packageDimensions,
      market,
      labels,
    );
    if (!parsedPackageDimensions.ok) {
      setPhysicalError(`包装尺寸：${parsedPackageDimensions.message}`);
      return;
    }
    const parsedPackageWeight = normalizeWeightInput(packageWeight, market, labels);
    if (!parsedPackageWeight.ok) {
      setPhysicalError(`包装重量：${parsedPackageWeight.message}`);
      return;
    }

    setPhysicalBusy(true);
    setPhysicalError("");
    setPhysicalNotice("");
    try {
      const updated = await updateProduct(productDetail.id, {
        dimensions_json: parsedDimensions.value,
        package_dimensions_json: parsedPackageDimensions.value,
        package_weight_json: parsedPackageWeight.value,
        weight_json: parsedWeight.value,
      });
      onProductPatched?.(updated);
      await onRefreshDetail(productDetail.id);
      setPhysicalNotice(
        "尺寸重量已保存。包装重量变了的话，到下面运费板块点「按规则重算」。",
      );
    } catch (error) {
      setPhysicalError(errorText(error, "尺寸重量保存失败，请重试。"));
    } finally {
      setPhysicalBusy(false);
    }
  }

  // ---------------------------------------------------------------- 变体编辑
  function updateVariant(index: number, updater: (row: VariantDossierRow) => VariantDossierRow) {
    setVariantsNotice("");
    setVariants((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? updater(row) : row)),
    );
  }

  function addVariant() {
    setVariantsNotice("");
    setVariants((current) => [
      ...current,
      {
        ...emptyVariantInput(),
        dimensions_input: { height: "", length: "", unit: units.dimensions, width: "" },
        variant_id: null,
        variant_sku: null,
        weight_input: { unit: units.weight, value: "" },
      },
    ]);
  }

  function removeVariant(index: number) {
    setVariantsNotice("");
    setVariants((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  function addVariantAttribute(index: number) {
    updateVariant(index, (row) => {
      const used = new Set(row.attributes.map((attribute) => attribute.type));
      const nextType =
        VARIANT_ATTRIBUTE_TYPES.find((type) => !used.has(type)) ??
        VARIANT_ATTRIBUTE_TYPES[0];
      return { ...row, attributes: [...row.attributes, { type: nextType, value: "" }] };
    });
  }

  function updateVariantAttribute(
    index: number,
    attributeIndex: number,
    field: "type" | "value",
    value: string,
  ) {
    updateVariant(index, (row) => ({
      ...row,
      attributes: row.attributes.map((attribute, position) =>
        position === attributeIndex
          ? field === "type"
            ? { ...attribute, type: value as ProductVariantAttributeType }
            : { ...attribute, value }
          : attribute,
      ),
    }));
  }

  function removeVariantAttribute(index: number, attributeIndex: number) {
    updateVariant(index, (row) => ({
      ...row,
      attributes: row.attributes.filter((_, position) => position !== attributeIndex),
    }));
  }

  function selectProductType(next: ProductTypeValue) {
    setVariantsNotice("");
    setVariantsError("");
    setProductType(next);
    if (next === "variable_product" && variants.length === 0) {
      addVariant();
    }
  }

  async function saveVariants() {
    let items: NonNullable<Parameters<typeof syncProductVariants>[1]["variants"]> = [];
    if (productType === "variable_product") {
      if (variants.length === 0) {
        setVariantsError(labels.variantRequired);
        return;
      }
      for (const [index, row] of variants.entries()) {
        if (row.attributes.every((attribute) => !attribute.value.trim())) {
          setVariantsError(`变体 ${index + 1}：至少填一个属性（颜色 / 尺码 / 功能 / 数量）。`);
          return;
        }
        if (hasDuplicateVariantAttributeTypes(row)) {
          setVariantsError(`变体 ${index + 1}：${labels.variantDuplicateAttributeTypes}`);
          return;
        }
      }
      const built = buildVariantPayloads(variants, market, labels);
      if (!built.ok) {
        setVariantsError(built.message);
        return;
      }
      items = built.value.map((payload, index) => ({
        ...payload,
        variant_id: variants[index]?.variant_id ?? null,
      }));
    }

    setVariantsBusy(true);
    setVariantsError("");
    setVariantsNotice("");
    setVariantReferenceOutcomes([]);
    try {
      const result = await syncProductVariants(productDetail.id, {
        product_type: productType,
        variants: items,
      });
      onProductPatched?.(result.product);
      await onRefreshDetail(productDetail.id);
      setVariants(
        (result.product.variants ?? []).map((variant) => variantFormFromRead(variant, units)),
      );
      setProductType(productTypeOf(result.product.product_type));
      setVariantReferenceOutcomes(result.reference_images);
      if (result.reference_images.some((item) => item.status === "stored")) {
        onRefreshWorkflow?.();
      }
      const count = result.product.variants?.length ?? 0;
      setVariantsNotice(
        productType === "variable_product"
          ? `已保存：多变体产品，${count} 个变体。价格可在下面「变体价格核对」继续改。`
          : "已保存：单产品，保留一条默认变体。",
      );
    } catch (error) {
      setVariantsError(errorText(error, "变体保存失败，请重试。"));
    } finally {
      setVariantsBusy(false);
    }
  }

  // ---------------------------------------------------------------- 参考图链接
  async function submitReferenceUrls() {
    const urls: string[] = [];
    for (const raw of referenceUrls) {
      const url = raw.trim();
      if (!url) {
        continue;
      }
      if (!/^https?:\/\//i.test(url)) {
        setReferenceError("参考图链接必须以 http:// 或 https:// 开头。");
        return;
      }
      if (!urls.includes(url)) {
        urls.push(url);
      }
    }
    if (urls.length === 0) {
      setReferenceError("先贴至少一条参考图链接。");
      return;
    }
    setReferenceBusy(true);
    setReferenceError("");
    setReferenceOutcomes([]);
    try {
      const result = await addProductReferenceImages(productDetail.id, {
        urls,
        variant_id: referenceTarget || null,
      });
      setReferenceOutcomes(result.items);
      const storedUrls = new Set(
        result.items.filter((item) => item.status === "stored").map((item) => item.url),
      );
      if (storedUrls.size > 0) {
        onProductPatched?.(result.product);
        await onRefreshDetail(productDetail.id);
        onRefreshWorkflow?.();
      }
      // 存成功的行清掉，失败的留在输入框里让人改。
      const remaining = referenceUrls.filter((raw) => !storedUrls.has(raw.trim()));
      setReferenceUrls(remaining.length ? remaining : [""]);
    } catch (error) {
      setReferenceError(errorText(error, "参考图入库失败，请重试。"));
    } finally {
      setReferenceBusy(false);
    }
  }

  async function deleteReferenceAsset(assetId: string) {
    if (!onDeleteMedia) {
      return;
    }
    setDeletingAssetId(assetId);
    setReferenceError("");
    try {
      await onDeleteMedia(assetId);
    } catch (error) {
      setReferenceError(errorText(error, "删除参考图失败，请重试。"));
    } finally {
      setDeletingAssetId(null);
    }
  }

  // ---------------------------------------------------------------- 渲染
  function renderDimensions(
    value: ProductDimensionsInput,
    onChange: (next: ProductDimensionsInput) => void,
    prefix: string,
  ) {
    return (
      <div className={styles.measurementGrid}>
        {(["length", "width", "height"] as const).map((field) => (
          <label className={styles.field} key={`${prefix}-${field}`}>
            <span>{labels[field]}</span>
            <input
              disabled={physicalBusy}
              inputMode="decimal"
              onChange={(event) => onChange({ ...value, [field]: event.target.value })}
              placeholder={field === "length" ? "10" : field === "width" ? "8" : "6"}
              value={value[field]}
            />
          </label>
        ))}
        <label className={styles.field}>
          <span>{labels.unit}</span>
          <select
            disabled={physicalBusy}
            onChange={(event) =>
              onChange({ ...value, unit: event.target.value as ProductDimensionsInput["unit"] })
            }
            value={value.unit}
          >
            <option value="cm">cm</option>
            <option value="inch">inch</option>
          </select>
        </label>
      </div>
    );
  }

  function renderWeight(
    value: ProductWeightInput,
    onChange: (next: ProductWeightInput) => void,
  ) {
    return (
      <div className={styles.measurementGrid}>
        <label className={styles.field}>
          <span>{labels.weightValue}</span>
          <input
            disabled={physicalBusy}
            inputMode="decimal"
            onChange={(event) => onChange({ ...value, value: event.target.value })}
            placeholder="2.5"
            value={value.value}
          />
        </label>
        <label className={styles.field}>
          <span>{labels.unit}</span>
          <select
            disabled={physicalBusy}
            onChange={(event) =>
              onChange({ ...value, unit: event.target.value as ProductWeightInput["unit"] })
            }
            value={value.unit}
          >
            <option value="kg">kg</option>
            <option value="lb">lb</option>
            <option value="g">g</option>
            <option value="oz">oz</option>
          </select>
        </label>
      </div>
    );
  }

  function renderOutcomes(items: ReferenceImageOutcome[]) {
    if (items.length === 0) {
      return null;
    }
    return (
      <ul className={dossierStyles.dossierOutcomes}>
        {items.map((item) => (
          <li data-status={item.status} key={`${item.url}-${item.variant_sku ?? ""}`}>
            <span>{item.status === "stored" ? "已存" : item.status === "skipped" ? "跳过" : "失败"}</span>
            <code>{item.url}</code>
            {item.error ? <em>{item.error}</em> : null}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby="k-basic-dossier" className={styles.workflowSection}>
      <div className={styles.sellingPointsHeading}>
        <div>
          <span className={styles.eyebrow}>基础档案</span>
          <h4 id="k-basic-dossier">类型与变体 · 尺寸重量 · 参考图链接</h4>
          <p className={styles.sectionHint}>
            新建表单里那几样，建好之后也能在这里改。F 搬进来的产品从这里补齐。
          </p>
        </div>
      </div>

      {/* ------------------------------------------------ 尺寸与重量 */}
      <div className={styles.formSection}>
        <div className={styles.formSectionHeading}>
          <h4>尺寸与重量</h4>
          <span>
            面向 {market.zhLabel} 买家按 {units.dimensions} / {units.weight} 存；填 cm / kg 也行，保存时自动换算。
            运费按包装重量算，没填包装时退回产品重量。
          </span>
        </div>
        <p className={styles.sectionHint}>产品尺寸</p>
        {renderDimensions(dimensions, setDimensions, "product")}
        <p className={styles.sectionHint}>产品重量</p>
        {renderWeight(weight, setWeight)}
        <p className={styles.sectionHint}>包装尺寸（运费用）</p>
        {renderDimensions(packageDimensions, setPackageDimensions, "package")}
        <p className={styles.sectionHint}>包装重量（运费用）</p>
        {renderWeight(packageWeight, setPackageWeight)}
        {physicalError ? (
          <p className={styles.sellingPointsError} role="alert">
            {physicalError}
          </p>
        ) : null}
        {physicalNotice ? (
          <p className={styles.spSaveNotice} role="status">
            {physicalNotice}
          </p>
        ) : null}
        <div className={styles.sectionFooter}>
          <span>留空 = 未知，不会编造。</span>
          <button
            className="primary-button"
            disabled={physicalBusy}
            onClick={() => void savePhysical()}
            type="button"
          >
            {physicalBusy ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存尺寸重量
          </button>
        </div>
      </div>

      {/* ------------------------------------------------ 类型与变体 */}
      <div className={styles.formSection}>
        <div className={styles.formSectionHeading}>
          <h4>类型与变体</h4>
          <span>{labels.variantEditorHint}</span>
          {productType === "variable_product" ? (
            <button
              className="secondary-button"
              disabled={variantsBusy}
              onClick={addVariant}
              type="button"
            >
              <Plus aria-hidden="true" size={15} />
              {labels.addVariant}
            </button>
          ) : null}
        </div>

        <label className={styles.field}>
          <span>产品类型</span>
          <select
            disabled={variantsBusy}
            onChange={(event) => selectProductType(event.target.value as ProductTypeValue)}
            value={productType}
          >
            <option value="simple_product">{labels.simpleProduct}</option>
            <option value="variable_product">{labels.variableProduct}</option>
          </select>
        </label>

        {productType === "simple_product" ? (
          <p className={styles.sectionHint}>
            单产品只有一条默认变体，价格在下面「变体价格核对」里改。
            {savedProductType === "variable_product"
              ? " 现在是多变体产品：保存为单产品会只保留第一条变体，其余删除（还绑着图片的会被拒绝，先去图片管理删图）。"
              : " 要分颜色 / 尺码 / 套装卖，就切成「多变体产品」。"}
          </p>
        ) : (
          <div className={styles.variantEditor}>
            {variants.map((variant, index) => {
              const displayName = formatVariantAttributes(variant.attributes);
              return (
                <section className={styles.variantRow} key={variant.variant_id ?? `new-${index}`}>
                  <div className={styles.variantPreview}>
                    <strong>
                      {labels.variantRowLabel} {index + 1}
                      {variant.variant_sku ? (
                        <span className={styles.variantPriceSku}> {variant.variant_sku}</span>
                      ) : (
                        <span className={styles.variantPriceSku}> 新建，保存后分配 SKU</span>
                      )}
                    </strong>
                    <span>{displayName || labels.variantNameEmpty}</span>
                    <button
                      className="secondary-button"
                      disabled={variantsBusy || variants.length <= 1}
                      onClick={() => removeVariant(index)}
                      type="button"
                    >
                      {labels.removeVariant}
                    </button>
                  </div>

                  <div className={styles.variantAttributeBuilder}>
                    {variant.attributes.length === 0 ? (
                      <p className={styles.variantEmpty}>{labels.variantNameEmpty}</p>
                    ) : null}
                    {variant.attributes.map((attribute, attributeIndex) => (
                      <div
                        className={styles.variantAttributeRow}
                        key={`${variant.variant_id ?? index}-${attributeIndex}`}
                      >
                        <label className={styles.field}>
                          <span>{labels.attributeType}</span>
                          <select
                            disabled={variantsBusy}
                            onChange={(event) =>
                              updateVariantAttribute(index, attributeIndex, "type", event.target.value)
                            }
                            value={attribute.type}
                          >
                            {VARIANT_ATTRIBUTE_TYPES.map((type) => (
                              <option key={type} value={type}>
                                {variantAttributeTypeLabel(type)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className={styles.field}>
                          <span>{labels.attributeValue}</span>
                          <input
                            disabled={variantsBusy}
                            onChange={(event) =>
                              updateVariantAttribute(index, attributeIndex, "value", event.target.value)
                            }
                            placeholder={attributePlaceholder(attribute.type)}
                            value={attribute.value}
                          />
                        </label>
                        <button
                          className="secondary-button"
                          disabled={variantsBusy}
                          onClick={() => removeVariantAttribute(index, attributeIndex)}
                          type="button"
                        >
                          {labels.removeVariant}
                        </button>
                      </div>
                    ))}
                    <button
                      className="secondary-button"
                      disabled={variantsBusy}
                      onClick={() => addVariantAttribute(index)}
                      type="button"
                    >
                      <Plus aria-hidden="true" size={15} />
                      {labels.addAttribute}
                    </button>
                  </div>

                  <div className={styles.variantGrid}>
                    <label className={styles.field}>
                      <span>{labels.priceOverride}（必填，USD）</span>
                      <input
                        disabled={variantsBusy}
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariant(index, (row) => ({
                            ...row,
                            price_override: event.target.value,
                          }))
                        }
                        placeholder="19.99"
                        value={variant.price_override}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>该色参考图链接（可选，同色填一张即可）</span>
                      <input
                        autoComplete="off"
                        disabled={variantsBusy}
                        inputMode="url"
                        onChange={(event) =>
                          updateVariant(index, (row) => ({
                            ...row,
                            reference_image_url: event.target.value,
                          }))
                        }
                        placeholder="贴该颜色实物图直链（1688 / Amazon）"
                        value={variant.reference_image_url}
                      />
                    </label>
                  </div>

                  <div className={styles.measurementGrid}>
                    {(["length", "width", "height"] as const).map((field) => (
                      <label className={styles.field} key={field}>
                        <span>{labels[field]}</span>
                        <input
                          disabled={variantsBusy}
                          inputMode="decimal"
                          onChange={(event) =>
                            updateVariant(index, (row) => ({
                              ...row,
                              dimensions_input: {
                                ...row.dimensions_input,
                                [field]: event.target.value,
                              },
                            }))
                          }
                          value={variant.dimensions_input[field]}
                        />
                      </label>
                    ))}
                    <label className={styles.field}>
                      <span>{labels.unit}</span>
                      <select
                        disabled={variantsBusy}
                        onChange={(event) =>
                          updateVariant(index, (row) => ({
                            ...row,
                            dimensions_input: {
                              ...row.dimensions_input,
                              unit: event.target.value as ProductDimensionsInput["unit"],
                            },
                          }))
                        }
                        value={variant.dimensions_input.unit}
                      >
                        <option value="cm">cm</option>
                        <option value="inch">inch</option>
                      </select>
                    </label>
                  </div>

                  <div className={styles.measurementGrid}>
                    <label className={styles.field}>
                      <span>{labels.weightValue}</span>
                      <input
                        disabled={variantsBusy}
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariant(index, (row) => ({
                            ...row,
                            weight_input: { ...row.weight_input, value: event.target.value },
                          }))
                        }
                        value={variant.weight_input.value}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.unit}</span>
                      <select
                        disabled={variantsBusy}
                        onChange={(event) =>
                          updateVariant(index, (row) => ({
                            ...row,
                            weight_input: {
                              ...row.weight_input,
                              unit: event.target.value as ProductWeightInput["unit"],
                            },
                          }))
                        }
                        value={variant.weight_input.unit}
                      >
                        <option value="kg">kg</option>
                        <option value="lb">lb</option>
                        <option value="g">g</option>
                        <option value="oz">oz</option>
                      </select>
                    </label>
                  </div>
                </section>
              );
            })}
          </div>
        )}

        {variantsError ? (
          <p className={styles.sellingPointsError} role="alert">
            {variantsError}
          </p>
        ) : null}
        {variantsNotice ? (
          <p className={styles.spSaveNotice} role="status">
            {variantsNotice}
          </p>
        ) : null}
        {renderOutcomes(variantReferenceOutcomes)}
        <div className={styles.sectionFooter}>
          <span>
            已有变体原地改，SKU 不变；删掉的变体如果还绑着图片会被拒绝。
          </span>
          <button
            className="primary-button"
            disabled={variantsBusy}
            onClick={() => void saveVariants()}
            type="button"
          >
            {variantsBusy ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <Save aria-hidden="true" size={16} />
            )}
            保存类型与变体
          </button>
        </div>
      </div>

      {/* ------------------------------------------------ 参考图链接 */}
      <div className={styles.formSection}>
        <div className={styles.formSectionHeading}>
          <h4>参考图链接</h4>
          <span>
            只收 1688（alicdn）/ Amazon 图片直链，逐条入库、逐条报结果。其他来源的图请在下面「图片管理」里本地上传。
          </span>
        </div>

        {referenceAssets.length > 0 ? (
          <ul className={dossierStyles.dossierReferenceList}>
            {referenceAssets.map((asset) => (
              <li key={asset.id}>
                <img
                  alt=""
                  decoding="async"
                  loading="lazy"
                  src={asset.file_url_placeholder || mediaAssetThumbnailUrl(asset.id)}
                />
                <div>
                  <strong>
                    {mediaVariantDisplayName(productDetail.variants, asset.variant_sku)}
                  </strong>
                  <span>{asset.object_key || asset.id}</span>
                </div>
                <button
                  className="secondary-button"
                  disabled={!onDeleteMedia || deletingAssetId === asset.id}
                  onClick={() => void deleteReferenceAsset(asset.id)}
                  type="button"
                >
                  {deletingAssetId === asset.id ? (
                    <LoaderCircle aria-hidden="true" className="spin" size={15} />
                  ) : (
                    <Trash2 aria-hidden="true" size={15} />
                  )}
                  删除
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.sellingPointsEmpty}>还没有参考图。</p>
        )}

        {savedProductType === "variable_product" && (productDetail.variants?.length ?? 0) > 0 ? (
          <label className={styles.field}>
            <span>挂到</span>
            <select
              disabled={referenceBusy}
              onChange={(event) => setReferenceTarget(event.target.value)}
              value={referenceTarget}
            >
              <option value="">产品级参考图</option>
              {(productDetail.variants ?? []).map((variant) => (
                <option key={variant.id} value={variant.id}>
                  {mediaVariantDisplayName(productDetail.variants, variant.variant_sku)}（该色专属）
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {referenceUrls.map((url, index) => (
          <div className={styles.workflowStartGrid} key={`reference-url-${index}`}>
            <label className={styles.field}>
              <span>参考图链接 {index + 1}</span>
              <input
                autoComplete="off"
                disabled={referenceBusy}
                inputMode="url"
                onChange={(event) =>
                  setReferenceUrls((current) =>
                    current.map((item, position) =>
                      position === index ? event.target.value : item,
                    ),
                  )
                }
                placeholder="https://cbu01.alicdn.com/img/ibank/…jpg"
                value={url}
              />
            </label>
            <button
              className="secondary-button"
              disabled={referenceBusy || referenceUrls.length <= 1}
              onClick={() =>
                setReferenceUrls((current) => current.filter((_, position) => position !== index))
              }
              type="button"
            >
              删除
            </button>
          </div>
        ))}
        <div>
          <button
            className="secondary-button"
            disabled={referenceBusy || referenceUrls.length >= 8}
            onClick={() => setReferenceUrls((current) => [...current, ""])}
            type="button"
          >
            <Plus aria-hidden="true" size={15} />
            再加一条
          </button>
        </div>

        {referenceError ? (
          <p className={styles.sellingPointsError} role="alert">
            {referenceError}
          </p>
        ) : null}
        {renderOutcomes(referenceOutcomes)}
        <div className={styles.sectionFooter}>
          <span>入库后会出现在上面的列表和「图片管理」里。</span>
          <button
            className="primary-button"
            disabled={referenceBusy}
            onClick={() => void submitReferenceUrls()}
            type="button"
          >
            {referenceBusy ? (
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
            ) : (
              <ImagePlus aria-hidden="true" size={16} />
            )}
            入库参考图
          </button>
        </div>
      </div>
    </section>
  );
}
