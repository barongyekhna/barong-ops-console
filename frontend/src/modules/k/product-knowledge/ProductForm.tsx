"use client";

import { Globe2, LoaderCircle, Plus, Ruler, Scale } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { searchCategories, type CategoryTreeItem } from "./api";

import styles from "./ProductKnowledge.module.css";
import { formatVariantAttributes, normalizeVariantAttributes } from "./display";
import type {
  ProductDimensionsInput,
  ProductFormValues,
  ProductManualSpecInput,
  ProductVariantAttributeInput,
  ProductVariantAttributeType,
  ProductVariantInput,
  ProductWeightInput,
} from "./types";
import {
  ACTIVE_FORM_LOCALE,
  attributePlaceholder,
  buildAttributes,
  buildMultilingualFields,
  buildVariantPayloads,
  emptyVariantInput,
  hasDuplicateVariantAttributeTypes,
  makeInitialValues,
  normalizeDimensionsInput,
  normalizePriceInput,
  normalizeWeightInput,
  optionalText,
  PRODUCT_FORM_LABELS,
  TARGET_MARKETS,
  targetMarketForCode,
  unitConversionSummary,
  VARIANT_ATTRIBUTE_TYPES,
  variantAttributeTypeLabel,
} from "./form-helpers";
import type {
  ProductFormProps,
  StringProductFormField,
} from "./form-helpers";


export function ProductForm({
  error,
  isSubmitting,
  onCreate,
  onDismissError,
}: ProductFormProps) {
  const labels = PRODUCT_FORM_LABELS[ACTIVE_FORM_LOCALE];
  const [values, setValues] = useState<ProductFormValues>(makeInitialValues);
  const [catQuery, setCatQuery] = useState("");
  const [catResults, setCatResults] = useState<CategoryTreeItem[]>([]);

  useEffect(() => {
    const term = catQuery.trim();
    if (!term) {
      setCatResults([]);
      return;
    }
    const tree = values.channel === "amazon" ? "amazon" : "google";
    const handle = window.setTimeout(() => {
      void searchCategories(tree, term)
        .then(setCatResults)
        .catch(() => setCatResults([]));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [catQuery, values.channel]);

  function selectChannel(nextChannel: string) {
    setValues((current) => ({
      ...current,
      channel: nextChannel,
      category_id: "",
      category_label: "",
    }));
    setCatQuery("");
    setCatResults([]);
  }
  function pickCategory(item: CategoryTreeItem) {
    setValues((current) => ({
      ...current,
      category_id: item.id,
      category_label: item.full_path,
    }));
    setCatQuery("");
    setCatResults([]);
  }
  function clearCategory() {
    setValues((current) => ({ ...current, category_id: "", category_label: "" }));
  }
  const submitLockRef = useRef(false);
  const [isLocallySubmitting, setIsLocallySubmitting] = useState(false);
  const [validationError, setValidationError] = useState("");

  const selectedMarket = targetMarketForCode(values.target_market) ?? TARGET_MARKETS[0];
  const submitLocked = isSubmitting || isLocallySubmitting;

  function clearFormErrors() {
    setValidationError("");
    if (error) {
      onDismissError();
    }
  }

  function updateValue(key: StringProductFormField, value: string) {
    setValues((current) => ({ ...current, [key]: value }));
    clearFormErrors();
  }

  function updateMarket(code: string) {
    const nextMarket = targetMarketForCode(code);
    if (!nextMarket) {
      setValidationError(labels.marketInvalid);
      return;
    }
    setValues((current) => ({
      ...current,
      price_currency: nextMarket.currency,
      target_market: nextMarket.code,
    }));
    clearFormErrors();
  }

  function updateDimensionValue(
    key: keyof ProductDimensionsInput,
    value: ProductDimensionsInput[keyof ProductDimensionsInput],
  ) {
    setValues((current) => ({
      ...current,
      dimensions_input: {
        ...current.dimensions_input,
        [key]: value,
      },
    }));
    clearFormErrors();
  }

  function updateWeightValue(
    key: keyof ProductWeightInput,
    value: ProductWeightInput[keyof ProductWeightInput],
  ) {
    setValues((current) => ({
      ...current,
      weight_input: {
        ...current.weight_input,
        [key]: value,
      },
    }));
    clearFormErrors();
  }

  function updateManualSpec(
    index: number,
    key: keyof ProductManualSpecInput,
    value: string,
  ) {
    setValues((current) => ({
      ...current,
      manual_specs: current.manual_specs.map((spec, specIndex) =>
        specIndex === index ? { ...spec, [key]: value } : spec,
      ),
    }));
    clearFormErrors();
  }

  function addManualSpec() {
    setValues((current) => ({
      ...current,
      manual_specs: [
        ...current.manual_specs,
        { label: "", value: "", unit: "" },
      ],
    }));
    clearFormErrors();
  }

  function removeManualSpec(index: number) {
    setValues((current) => ({
      ...current,
      manual_specs: current.manual_specs.filter(
        (_, specIndex) => specIndex !== index,
      ),
    }));
    clearFormErrors();
  }

  function updatePackageItem(index: number, value: string) {
    setValues((current) => ({
      ...current,
      package_includes: current.package_includes.map((item, itemIndex) =>
        itemIndex === index ? value : item,
      ),
    }));
    clearFormErrors();
  }

  function addPackageItem() {
    setValues((current) => ({
      ...current,
      package_includes: [...current.package_includes, ""],
    }));
    clearFormErrors();
  }

  function removePackageItem(index: number) {
    setValues((current) => ({
      ...current,
      package_includes: current.package_includes.filter(
        (_, itemIndex) => itemIndex !== index,
      ),
    }));
    clearFormErrors();
  }

  function updateVariantReferenceUrl(index: number, value: string) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index
          ? { ...variant, reference_image_url: value }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function updateVariantPrice(index: number, value: string) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index ? { ...variant, price_override: value } : variant,
      ),
    }));
    clearFormErrors();
  }

  function updateVariantDimension(
    index: number,
    key: keyof ProductDimensionsInput,
    value: ProductDimensionsInput[keyof ProductDimensionsInput],
  ) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index
          ? {
              ...variant,
              dimensions_input: { ...variant.dimensions_input, [key]: value },
            }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function updateVariantWeight(
    index: number,
    key: keyof ProductWeightInput,
    value: ProductWeightInput[keyof ProductWeightInput],
  ) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index
          ? {
              ...variant,
              weight_input: { ...variant.weight_input, [key]: value },
            }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function updateReferenceImageUrl(index: number, value: string) {
    setValues((current) => ({
      ...current,
      reference_image_urls: current.reference_image_urls.map(
        (item, itemIndex) => (itemIndex === index ? value : item),
      ),
    }));
    clearFormErrors();
  }

  function addReferenceImageUrl() {
    setValues((current) => ({
      ...current,
      reference_image_urls: [...current.reference_image_urls, ""],
    }));
    clearFormErrors();
  }

  function removeReferenceImageUrl(index: number) {
    setValues((current) => ({
      ...current,
      reference_image_urls: current.reference_image_urls.filter(
        (_, itemIndex) => itemIndex !== index,
      ),
    }));
    clearFormErrors();
  }

  function updateExtraKeyword(index: number, value: string) {
    setValues((current) => ({
      ...current,
      extra_keywords: current.extra_keywords.map((item, itemIndex) =>
        itemIndex === index ? value : item,
      ),
    }));
    clearFormErrors();
  }

  function addExtraKeyword() {
    setValues((current) => ({
      ...current,
      extra_keywords: [...current.extra_keywords, ""],
    }));
    clearFormErrors();
  }

  function removeExtraKeyword(index: number) {
    setValues((current) => ({
      ...current,
      extra_keywords: current.extra_keywords.filter(
        (_, itemIndex) => itemIndex !== index,
      ),
    }));
    clearFormErrors();
  }

  function updateVariantAttribute(
    variantIndex: number,
    attributeIndex: number,
    key: keyof ProductVariantAttributeInput,
    value: string,
  ) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, currentVariantIndex) =>
        currentVariantIndex === variantIndex
          ? {
              ...variant,
              attributes: variant.attributes.map((attribute, currentAttributeIndex) =>
                currentAttributeIndex === attributeIndex
                  ? key === "type"
                    ? {
                        ...attribute,
                        type: value as ProductVariantAttributeType,
                      }
                    : { ...attribute, value }
                  : attribute,
              ),
            }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function addVariantAttribute(variantIndex: number) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, currentVariantIndex) =>
        currentVariantIndex === variantIndex
          ? {
              ...variant,
              attributes: [
                ...variant.attributes,
                {
                  type: "size",
                  value: "",
                },
              ],
            }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function removeVariantAttribute(variantIndex: number, attributeIndex: number) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, currentVariantIndex) =>
        currentVariantIndex === variantIndex
          ? {
              ...variant,
              attributes: variant.attributes.filter(
                (_, currentAttributeIndex) =>
                  currentAttributeIndex !== attributeIndex,
              ),
            }
          : variant,
      ),
    }));
    clearFormErrors();
  }

  function addVariant() {
    setValues((current) => ({
      ...current,
      product_type: "variable_product",
      variants: [...current.variants, emptyVariantInput()],
    }));
    clearFormErrors();
  }

  function removeVariant(index: number) {
    setValues((current) => ({
      ...current,
      variants: current.variants.filter((_, variantIndex) => variantIndex !== index),
    }));
    clearFormErrors();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLockRef.current || isSubmitting) {
      return;
    }

    const mainKeyword = values.main_keyword.trim();
    const rawInputText = values.raw_input_text.trim();
    const market = targetMarketForCode(values.target_market);

    if (!market) {
      setValidationError(labels.marketInvalid);
      return;
    }
    if (!values.category_id) {
      setValidationError(
        "请先选择类目——SKU 由系统按「叶子类目简写-编号」自动分配（如 IGL-001），不允许手填。",
      );
      return;
    }
    if (!mainKeyword || !rawInputText || !values.target_market) {
      setValidationError(labels.fieldRequired);
      return;
    }
    const sourceUrl = values.source_url.trim();
    if (sourceUrl && !/^https?:\/\//i.test(sourceUrl)) {
      setValidationError("货源链接必须以 http:// 或 https:// 开头（可留空）。");
      return;
    }
    const referenceImageUrls = values.reference_image_urls
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item, index, list) => list.indexOf(item) === index);
    if (referenceImageUrls.some((item) => !/^https?:\/\//i.test(item))) {
      setValidationError("参考图链接必须以 http:// 或 https:// 开头（可留空）。");
      return;
    }
    if (values.product_type === "variable_product" && values.variants.length === 0) {
      setValidationError(labels.variantRequired);
      return;
    }
    if (
      values.product_type === "variable_product" &&
      values.variants.some(
        (variant) => normalizeVariantAttributes(variant.attributes).length === 0,
      )
    ) {
      setValidationError(labels.variantAttributesRequired);
      return;
    }
    if (
      values.product_type === "variable_product" &&
      values.variants.some(hasDuplicateVariantAttributeTypes)
    ) {
      setValidationError(labels.variantDuplicateAttributeTypes);
      return;
    }

    const isVariable = values.product_type === "variable_product";

    // 多变体产品(2026-07-22 用户拍板):价格/尺寸/重量全部按变体填写,
    // 父体这三项一律不收——1 个装和 2 个装的物理规格与价格本来就不同。
    const dimensions = isVariable
      ? { ok: true as const, value: null }
      : normalizeDimensionsInput(values.dimensions_input, market, labels);
    if (!dimensions.ok) {
      setValidationError(dimensions.message);
      return;
    }

    const weight = isVariable
      ? { ok: true as const, value: null }
      : normalizeWeightInput(values.weight_input, market, labels);
    if (!weight.ok) {
      setValidationError(weight.message);
      return;
    }

    const price = isVariable
      ? { ok: true as const, value: null }
      : normalizePriceInput(
          values.price_value,
          values.price_currency,
          market,
          labels,
        );
    if (!price.ok) {
      setValidationError(price.message);
      return;
    }

    const variantsResult = isVariable
      ? buildVariantPayloads(values.variants, market, labels)
      : { ok: true as const, value: [] as ProductVariantInput[] };
    if (!variantsResult.ok) {
      setValidationError(variantsResult.message);
      return;
    }
    const variants = variantsResult.value;

    const extraKeywords = values.extra_keywords
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item, index, list) => list.indexOf(item) === index)
      .filter((item) => item.toLowerCase() !== mainKeyword.toLowerCase());

    const populatedManualSpecs = values.manual_specs.filter(
      (spec) => spec.label.trim() || spec.value.trim() || spec.unit.trim(),
    );
    if (
      populatedManualSpecs.some(
        (spec) => !spec.label.trim() || !spec.value.trim(),
      )
    ) {
      setValidationError("每条规格都必须同时填写规格名和真实值；未知项请留空。");
      return;
    }
    const packageIncludes = values.package_includes
      .map((item) => item.trim())
      .filter(Boolean);
    if (packageIncludes.some((item) => /[\u3400-\u9fff]/u.test(item))) {
      setValidationError("包装清单必须逐项使用英文，不能包含中文。");
      return;
    }
    const structuredSpecs =
      populatedManualSpecs.length > 0
        ? {
            schema_version: "1.0",
            source: { platform: "operator" },
            additional_specs: populatedManualSpecs.map((spec, index) => ({
              evidence: "operator_fact",
              key: `operator_attribute_${index + 1}`,
              label: spec.label.trim(),
              raw_value: spec.value.trim(),
              unit: spec.unit.trim() || undefined,
              value: spec.value.trim(),
            })),
          }
        : null;

    const multilingualFields = buildMultilingualFields(values, market);
    const attributes = buildAttributes({
      dimensions: dimensions.value,
      market,
      multilingualFields,
      price: price.value,
      weight: weight.value,
    });
    attributes.push({
      attribute_group: "sku_system",
      attribute_key: "sku_structure",
      attribute_value_json: {
        parent_sku: "backend_allocated_from_leaf_category",
        product_type: values.product_type,
        variant_identity: "backend_generated_internal_id",
        variants:
          values.product_type === "variable_product"
            ? values.variants.map((variant) => ({
                attributes: normalizeVariantAttributes(variant.attributes),
                display_name: formatVariantAttributes(variant.attributes),
              }))
            : [],
      },
      source: "frontend_product_form",
    });
    const frontendSchemaSnapshot = {
      deepseek: {
        provider: "deepseek",
        trigger: "after_product_create",
      },
      dimensions_input: dimensions.value,
      multilingual_fields: multilingualFields,
      main_keyword: mainKeyword,
      extra_keywords: extraKeywords,
      reference_image_urls: referenceImageUrls,
      parent_sku: "backend_allocated_from_leaf_category",
      price_input: price.value,
      auto_key: "backend_generated_immutable",
      product_type: values.product_type,
      schema: "product_create_form_v3_sku_variant",
      target_market: {
        code: market.code,
        label: market.label,
        locale: market.contentLocale,
        unit_profile: market.unitProfile,
      },
      variants:
        values.product_type === "variable_product"
          ? values.variants.map((variant) => ({
              attributes: normalizeVariantAttributes(variant.attributes),
              display_name: formatVariantAttributes(variant.attributes),
              price_override: variant.price_override,
            }))
          : [],
      weight_input: weight.value,
    };

    submitLockRef.current = true;
    setIsLocallySubmitting(true);
    try {
      await onCreate({
        attributes,
        brand_name: optionalText(values.brand_name),
        source_url: optionalText(values.source_url),
        reference_image_url: referenceImageUrls[0] ?? null,
        reference_image_urls:
          referenceImageUrls.length > 0 ? referenceImageUrls : null,
        keywords:
          extraKeywords.length > 0
            ? extraKeywords.map((keyword) => ({
                keyword_text: keyword,
                keyword_type: "secondary" as const,
                language_code: market.contentLocale,
                market: market.code,
                source: "operator_manual",
                status: "candidate" as const,
                reason: "建品表单手动录入",
              }))
            : undefined,
        dimensions_json: dimensions.value,
        long_description_en: rawInputText,
        main_keyword: mainKeyword,
        manual_notes: JSON.stringify(frontendSchemaSnapshot, null, 2),
        price_currency: price.value?.currency ?? values.price_currency,
        product_name_en: optionalText(values.product_name_en),
        product_status: "draft",
        product_type: values.product_type,
        channel: values.channel,
        category_id: values.category_id || null,
        festival_style: values.festival_style || null,
        regular_price: price.value?.value ?? null,
        raw_input_text: rawInputText,
        review_status: "draft",
        short_description_en: rawInputText,
        source_system: "manual",
        target_locale: market.contentLocale,
        target_market: market.code,
        target_market_label: market.label,
        variants,
        weight_json: weight.value,
        package_includes_json: packageIncludes.length > 0 ? packageIncludes : null,
        structured_specs_json: structuredSpecs,
      });
      setValues(makeInitialValues());
    } catch {
      // The parent renders the API error; keep the entered values for retry.
    } finally {
      submitLockRef.current = false;
      setIsLocallySubmitting(false);
    }
  }

  const formError = validationError || error;

  return (
    <form
      aria-label="创建产品知识产品"
      className={styles.form}
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className={styles.panelHeading}>
        <div>
          <span className={styles.eyebrow}>{labels.create}</span>
          <h3>{labels.newProduct}</h3>
        </div>
      </div>

      <section className={styles.formSection} aria-labelledby="k-product-info">
        <div className={styles.formSectionHeading}>
          <h4 id="k-product-info">{labels.productInfo}</h4>
        </div>

        <div className={styles.formGrid}>
          <div className={styles.autoKeyNotice}>
            <strong>产品键</strong>
            <span>{labels.productKeyAuto}</span>
          </div>

          <label className={styles.field}>
            <span>{labels.name}</span>
            <input
              autoComplete="off"
              onChange={(event) =>
                updateValue("product_name_en", event.target.value)
              }
              placeholder="不锈钢泵"
              value={values.product_name_en}
            />
          </label>

          <label className={styles.field}>
            <span>{labels.mainKeyword}</span>
            <input
              autoComplete="off"
              onChange={(event) => updateValue("main_keyword", event.target.value)}
              placeholder={labels.mainKeywordPlaceholder}
              required
              value={values.main_keyword}
            />
          </label>

          {values.extra_keywords.map((keyword, index) => (
            <label className={styles.field} key={`extra-keyword-${index}`}>
              <span>更多关键词 {index + 1}（可选）</span>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  autoComplete="off"
                  onChange={(event) =>
                    updateExtraKeyword(index, event.target.value)
                  }
                  placeholder="一格一条，随产品进入关键词库"
                  style={{ flex: 1 }}
                  value={keyword}
                />
                <button
                  className="secondary-button"
                  disabled={values.extra_keywords.length <= 1}
                  onClick={() => removeExtraKeyword(index)}
                  type="button"
                >
                  删除
                </button>
              </div>
            </label>
          ))}
          <div className={styles.field}>
            <span aria-hidden="true">&nbsp;</span>
            <button
              className="secondary-button"
              onClick={addExtraKeyword}
              type="button"
            >
              <Plus aria-hidden="true" size={15} />
              添加关键词
            </button>
          </div>

          <label className={styles.field}>
            <span>SKU（自动分配）</span>
            <input
              disabled
              placeholder="选择类目后自动生成：叶子类目简写-编号（如 IGL-001）"
              value=""
            />
          </label>

          <label className={styles.field}>
            <span>{labels.brand}</span>
            <input
              autoComplete="off"
              onChange={(event) =>
                updateValue("brand_name", event.target.value)
              }
              placeholder="品牌"
              value={values.brand_name}
            />
          </label>

          <label className={styles.field}>
            <span>1688 货源链接（可选）</span>
            <input
              autoComplete="off"
              inputMode="url"
              onChange={(event) =>
                updateValue("source_url", event.target.value)
              }
              placeholder="粘贴 1688 商品页链接，出单后一键直达货源；可留空后补"
              value={values.source_url}
            />
          </label>

          {values.reference_image_urls.map((url, index) => (
            <label className={styles.field} key={`reference-image-${index}`}>
              <span>参考图链接 {index + 1}（可选）</span>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  autoComplete="off"
                  inputMode="url"
                  onChange={(event) =>
                    updateReferenceImageUrl(index, event.target.value)
                  }
                  placeholder="1688 图片右键「复制图片地址」贴这里；第一条为主参考图"
                  style={{ flex: 1 }}
                  value={url}
                />
                <button
                  className="secondary-button"
                  disabled={values.reference_image_urls.length <= 1}
                  onClick={() => removeReferenceImageUrl(index)}
                  type="button"
                >
                  删除
                </button>
              </div>
            </label>
          ))}
          <div className={styles.field}>
            <span aria-hidden="true">&nbsp;</span>
            <button
              className="secondary-button"
              onClick={addReferenceImageUrl}
              type="button"
            >
              <Plus aria-hidden="true" size={15} />
              添加参考图链接
            </button>
          </div>

          <label className={styles.field}>
            <span>{labels.productType}</span>
            <select
              onChange={(event) =>
                updateValue(
                  "product_type",
                  event.target.value as ProductFormValues["product_type"],
                )
              }
              value={values.product_type}
            >
              <option value="simple_product">{labels.simpleProduct}</option>
              <option value="variable_product">{labels.variableProduct}</option>
            </select>
          </label>

          <label className={styles.field}>
            <span>节日风格（可选，轻氛围）</span>
            <select
              onChange={(event) =>
                updateValue("festival_style", event.target.value)
              }
              value={values.festival_style}
            >
              <option value="">无（家规纯净背景）</option>
              <option value="halloween">万圣节 Halloween</option>
              <option value="christmas">圣诞节 Christmas</option>
              <option value="valentines">情人节 Valentine's</option>
              <option value="thanksgiving">感恩节 Thanksgiving</option>
              <option value="easter">复活节 Easter</option>
              <option value="new_year">新年 New Year</option>
            </select>
            <small style={{ color: "var(--mm-muted, var(--color-muted))", fontSize: "0.78rem" }}>
              只给场景图/描述图加节日氛围；主图和各颜色变体主图始终保持纯净背景（合规底线）。
            </small>
          </label>

          <div className={styles.inlineFields}>
            {values.product_type === "variable_product" ? (
              <div className={styles.field}>
                <span>{labels.price}</span>
                <span style={{ fontSize: "0.8rem", opacity: 0.75 }}>
                  多变体产品不设父体价格——请在下方每个变体卡片里分别填写价格。
                </span>
              </div>
            ) : (
              <label className={styles.field}>
                <span>{labels.price}</span>
                <input
                  inputMode="decimal"
                  onChange={(event) =>
                    updateValue("price_value", event.target.value)
                  }
                  placeholder="99.00"
                  value={values.price_value}
                />
              </label>
            )}
            <label className={styles.field}>
              <span>{labels.currency}</span>
              <select
                onChange={(event) =>
                  updateValue("price_currency", event.target.value)
                }
                value={values.price_currency}
              >
                {[
                  "USD",
                  "GBP",
                  "EUR",
                  "RUB",
                  "CNY",
                  "HKD",
                  "MOP",
                  "TWD",
                  "JPY",
                  "KRW",
                  "BRL",
                  "MXN",
                  "ARS",
                  "AED",
                ].map((currency) => (
                  <option key={currency} value={currency}>
                    {currency}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </section>

      <section className={styles.formSection} aria-labelledby="k-channel-category">
        <div className={styles.formSectionHeading}>
          <h4 id="k-channel-category">渠道与类目</h4>
        </div>
        <div className={styles.formGrid}>
          <div className={styles.field}>
            <span>产品分组</span>
            <div className={styles.inlineFields}>
              <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                <input
                  checked={values.channel === "dtc"}
                  name="k-channel"
                  onChange={() => selectChannel("dtc")}
                  type="radio"
                />
                独立站
              </label>
              <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                <input
                  checked={values.channel === "amazon"}
                  name="k-channel"
                  onChange={() => selectChannel("amazon")}
                  type="radio"
                />
                亚马逊
              </label>
            </div>
          </div>
          <label className={styles.field}>
            <span>
              类目（{values.channel === "amazon" ? "亚马逊" : "Google 独立站"}树）
            </span>
            {values.category_label ? (
              <span
                style={{
                  display: "inline-flex",
                  gap: 8,
                  alignItems: "center",
                  fontSize: "0.82rem",
                  color: "var(--mm-cyan, var(--color-primary-strong))",
                  marginBottom: 6,
                }}
              >
                已选：{values.category_label}
                <button
                  onClick={clearCategory}
                  style={{
                    background: "transparent",
                    border: "1px solid currentColor",
                    borderRadius: 6,
                    color: "inherit",
                    cursor: "pointer",
                    fontSize: "0.72rem",
                    padding: "1px 7px",
                  }}
                  type="button"
                >
                  清除
                </button>
              </span>
            ) : null}
            <input
              onChange={(event) => setCatQuery(event.target.value)}
              placeholder={`搜索${values.channel === "amazon" ? "亚马逊" : "独立站"}类目…`}
              type="search"
              value={catQuery}
            />
            {catResults.length > 0 ? (
              <ul
                style={{
                  listStyle: "none",
                  margin: "6px 0 0",
                  padding: 0,
                  maxHeight: 220,
                  overflowY: "auto",
                  border: "1px solid var(--mm-line, color-mix(in srgb, var(--color-primary) 18%, transparent))",
                  borderRadius: 8,
                  background: "color-mix(in srgb, var(--color-panel-base) 60%, transparent)",
                }}
              >
                {catResults.map((item) => (
                  <li key={item.id}>
                    <button
                      onClick={() => pickCategory(item)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        padding: "6px 10px",
                        background: "transparent",
                        border: "none",
                        color: "inherit",
                        cursor: "pointer",
                        fontSize: "0.82rem",
                      }}
                      type="button"
                    >
                      {item.full_path}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </label>
        </div>
      </section>

      <section className={styles.formSection} aria-labelledby="k-target-market">
        <div className={styles.formSectionHeading}>
          <Globe2 aria-hidden="true" size={18} />
          <h4 id="k-target-market">{labels.market}</h4>
          <span>{labels.targetMarketStatus}</span>
        </div>

        <div className={styles.formGrid}>
          <label className={styles.field}>
            <span>{labels.market}</span>
            <select
              onChange={(event) => updateMarket(event.target.value)}
              required
              value={values.target_market}
            >
              {TARGET_MARKETS.map((market) => (
                <option key={market.code} value={market.code}>
                  {market.zhLabel} ({market.code})
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {values.product_type !== "variable_product" ? (
      <>
      <section className={styles.formSection} aria-labelledby="k-dimensions">
        <div className={styles.formSectionHeading}>
          <Ruler aria-hidden="true" size={18} />
          <h4 id="k-dimensions">{labels.dimensions}</h4>
          <span>
            {labels.unitConversionHint}: {unitConversionSummary(selectedMarket)}
          </span>
        </div>

        <div className={styles.measurementGrid}>
          <label className={styles.field}>
            <span>{labels.length}</span>
            <input
              inputMode="decimal"
              onChange={(event) =>
                updateDimensionValue("length", event.target.value)
              }
              placeholder="10"
              value={values.dimensions_input.length}
            />
          </label>
          <label className={styles.field}>
            <span>{labels.width}</span>
            <input
              inputMode="decimal"
              onChange={(event) =>
                updateDimensionValue("width", event.target.value)
              }
              placeholder="8"
              value={values.dimensions_input.width}
            />
          </label>
          <label className={styles.field}>
            <span>{labels.height}</span>
            <input
              inputMode="decimal"
              onChange={(event) =>
                updateDimensionValue("height", event.target.value)
              }
              placeholder="6"
              value={values.dimensions_input.height}
            />
          </label>
          <label className={styles.field}>
            <span>{labels.unit}</span>
            <select
              onChange={(event) =>
                updateDimensionValue(
                  "unit",
                  event.target.value as ProductDimensionsInput["unit"],
                )
              }
              value={values.dimensions_input.unit}
            >
              <option value="cm">cm</option>
              <option value="inch">inch</option>
            </select>
          </label>
        </div>
      </section>

      <section className={styles.formSection} aria-labelledby="k-weight">
        <div className={styles.formSectionHeading}>
          <Scale aria-hidden="true" size={18} />
          <h4 id="k-weight">{labels.weight}</h4>
          <span>
            {labels.unitConversionHint}: {unitConversionSummary(selectedMarket)}
          </span>
        </div>

        <div className={styles.measurementGrid}>
          <label className={styles.field}>
            <span>{labels.weightValue}</span>
            <input
              inputMode="decimal"
              onChange={(event) =>
                updateWeightValue("value", event.target.value)
              }
              placeholder="2.5"
              value={values.weight_input.value}
            />
          </label>
          <label className={styles.field}>
            <span>{labels.unit}</span>
            <select
              onChange={(event) =>
                updateWeightValue(
                  "unit",
                  event.target.value as ProductWeightInput["unit"],
                )
              }
              value={values.weight_input.unit}
            >
              <option value="kg">kg</option>
              <option value="lb">lb</option>
              <option value="g">g</option>
              <option value="oz">oz</option>
            </select>
          </label>
        </div>
      </section>
      </>
      ) : null}

      <section className={styles.formSection} aria-labelledby="k-manual-specs">
        <div className={styles.formSectionHeading}>
          <h4 id="k-manual-specs">规格（事实）</h4>
          <span>只填写已核实事实；未知项留空，不要在这里写营销卖点。</span>
          <button className="secondary-button" onClick={addManualSpec} type="button">
            <Plus aria-hidden="true" size={15} />
            添加规格
          </button>
        </div>
        {values.manual_specs.map((spec, index) => (
          <div className={styles.measurementGrid} key={`manual-spec-${index}`}>
            <label className={styles.field}>
              <span>规格名</span>
              <input
                onChange={(event) =>
                  updateManualSpec(index, "label", event.target.value)
                }
                placeholder="例如：点火方式"
                value={spec.label}
              />
            </label>
            <label className={styles.field}>
              <span>真实值</span>
              <input
                onChange={(event) =>
                  updateManualSpec(index, "value", event.target.value)
                }
                placeholder="例如：压电点火"
                value={spec.value}
              />
            </label>
            <label className={styles.field}>
              <span>单位（可选）</span>
              <input
                onChange={(event) =>
                  updateManualSpec(index, "unit", event.target.value)
                }
                placeholder="inch / lb / W"
                value={spec.unit}
              />
            </label>
            <button
              className="secondary-button"
              disabled={values.manual_specs.length <= 1}
              onClick={() => removeManualSpec(index)}
              type="button"
            >
              删除
            </button>
          </div>
        ))}
      </section>

      <section className={styles.formSection} aria-labelledby="k-package-includes">
        <div className={styles.formSectionHeading}>
          <h4 id="k-package-includes">包装清单 (What's in the box)</h4>
          <span>每行一个真实组件，必须用英文；未知项留空。</span>
          <button className="secondary-button" onClick={addPackageItem} type="button">
            <Plus aria-hidden="true" size={15} />
            添加组件
          </button>
        </div>
        {values.package_includes.map((item, index) => (
          <div className={styles.measurementGrid} key={`package-item-${index}`}>
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
              disabled={values.package_includes.length <= 1}
              onClick={() => removePackageItem(index)}
              type="button"
            >
              删除
            </button>
          </div>
        ))}
      </section>

      {values.product_type === "variable_product" ? (
        <section className={styles.formSection} aria-labelledby="k-variants">
          <div className={styles.formSectionHeading}>
            <h4 id="k-variants">{labels.variants}</h4>
            <span>{labels.variantEditorHint}</span>
            <button className="secondary-button" onClick={addVariant} type="button">
              <Plus aria-hidden="true" size={15} />
              {labels.addVariant}
            </button>
          </div>

          <div className={styles.variantEditor}>
            {values.variants.map((variant, index) => {
              const displayName = formatVariantAttributes(variant.attributes);

              return (
                <section className={styles.variantRow} key={index}>
                  <div className={styles.variantPreview}>
                    <strong>
                      {labels.variantRowLabel} {index + 1}
                    </strong>
                    <span>{displayName || labels.variantNameEmpty}</span>
                    <button
                      className="secondary-button"
                      disabled={values.variants.length <= 1}
                      onClick={() => removeVariant(index)}
                      type="button"
                    >
                      {labels.removeVariant}
                    </button>
                  </div>

                  <div className={styles.variantAttributeBuilder}>
                    {variant.attributes.length === 0 ? (
                      <p className={styles.variantEmpty}>
                        {labels.variantNameEmpty}
                      </p>
                    ) : null}

                    {variant.attributes.map((attribute, attributeIndex) => (
                      <div
                        className={styles.variantAttributeRow}
                        key={`${index}-${attributeIndex}`}
                      >
                        <label className={styles.field}>
                          <span>{labels.attributeType}</span>
                          <select
                            onChange={(event) =>
                              updateVariantAttribute(
                                index,
                                attributeIndex,
                                "type",
                                event.target.value,
                              )
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
                            onChange={(event) =>
                              updateVariantAttribute(
                                index,
                                attributeIndex,
                                "value",
                                event.target.value,
                              )
                            }
                            placeholder={attributePlaceholder(attribute.type)}
                            value={attribute.value}
                          />
                        </label>
                        <button
                          className="secondary-button"
                          onClick={() =>
                            removeVariantAttribute(index, attributeIndex)
                          }
                          type="button"
                        >
                          {labels.removeVariant}
                        </button>
                      </div>
                    ))}

                    <button
                      className="secondary-button"
                      onClick={() => addVariantAttribute(index)}
                      type="button"
                    >
                      <Plus aria-hidden="true" size={15} />
                      {labels.addAttribute}
                    </button>
                  </div>

                  <div className={styles.variantGrid}>
                    <label className={styles.field}>
                      <span>
                        {labels.priceOverride}（必填，{values.price_currency}）
                      </span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantPrice(index, event.target.value)
                        }
                        placeholder="19.99"
                        required
                        value={variant.price_override}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>该色参考图链接（可选，同色填一张即可）</span>
                      <input
                        autoComplete="off"
                        inputMode="url"
                        onChange={(event) =>
                          updateVariantReferenceUrl(index, event.target.value)
                        }
                        placeholder="贴该颜色实物图；作图自动出该色主图，买家选色即换图"
                        value={variant.reference_image_url}
                      />
                    </label>
                  </div>

                  <div className={styles.measurementGrid}>
                    <label className={styles.field}>
                      <span>{labels.length}</span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantDimension(
                            index,
                            "length",
                            event.target.value,
                          )
                        }
                        placeholder="10"
                        value={variant.dimensions_input.length}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.width}</span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantDimension(
                            index,
                            "width",
                            event.target.value,
                          )
                        }
                        placeholder="8"
                        value={variant.dimensions_input.width}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.height}</span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantDimension(
                            index,
                            "height",
                            event.target.value,
                          )
                        }
                        placeholder="6"
                        value={variant.dimensions_input.height}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.unit}</span>
                      <select
                        onChange={(event) =>
                          updateVariantDimension(
                            index,
                            "unit",
                            event.target.value as ProductDimensionsInput["unit"],
                          )
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
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantWeight(index, "value", event.target.value)
                        }
                        placeholder="2.5"
                        value={variant.weight_input.value}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.unit}</span>
                      <select
                        onChange={(event) =>
                          updateVariantWeight(
                            index,
                            "unit",
                            event.target.value as ProductWeightInput["unit"],
                          )
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
        </section>
      ) : null}

      <label className={styles.field}>
        {/* M9 (QA 2026-08-22): mark description as required (it is enforced but
            was the only required field with no marker, so an empty submit looked
            like a dead button). */}
        <span>
          {labels.description}
          <span aria-hidden="true" style={{ color: "var(--color-error)" }}>
            {" "}
            *
          </span>
        </span>
        <textarea
          onChange={(event) => updateValue("raw_input_text", event.target.value)}
          placeholder={labels.descriptionPlaceholder}
          required
          rows={5}
          value={values.raw_input_text}
        />
      </label>

      <p className={styles.formMessage} role={formError ? "alert" : undefined}>
        {formError}
      </p>

      <div className={styles.formFooter}>
        <button
          className={`primary-button ${styles.formSubmitButton}`}
          disabled={submitLocked}
          type="submit"
        >
          {submitLocked ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          {submitLocked ? labels.creating : labels.createProduct}
        </button>
      </div>
    </form>
  );
}
