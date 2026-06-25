"use client";

import { Globe2, LoaderCircle, Plus, Ruler, Scale } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import styles from "./ProductKnowledge.module.css";
import type {
  ProductDimensionsInput,
  ProductCreateFormPayload,
  ProductFormValues,
  ProductKnowledgeAttributeInput,
  ProductVariantFormInput,
  ProductVariantInput,
  ProductWeightInput,
} from "./types";

type UiLocale = "zh" | "en";
type UnitProfile = "US" | "UK" | "EU" | "CN" | "METRIC";
type StringProductFormField = {
  [Key in keyof ProductFormValues]: ProductFormValues[Key] extends string
    ? Key
    : never;
}[keyof ProductFormValues];

type TargetMarketOption = {
  code: string;
  label: string;
  zhLabel: string;
  unitProfile: UnitProfile;
  contentLocale: string;
  currency: string;
};

type NormalizedDimensions = {
  length: number;
  width: number;
  height: number;
  unit: ProductDimensionsInput["unit"];
  source: {
    length: number;
    width: number;
    height: number;
    unit: ProductDimensionsInput["unit"];
  };
  target_market: string;
  target_market_label: string;
};

type NormalizedWeight = {
  value: number;
  unit: ProductWeightInput["unit"];
  source: {
    value: number;
    unit: ProductWeightInput["unit"];
  };
  target_market: string;
  target_market_label: string;
};

type NormalizedPrice = {
  value: number;
  currency: string;
  target_market: string;
  target_market_label: string;
};

type FieldResult<T> =
  | {
      ok: true;
      value: T | null;
    }
  | {
      ok: false;
      message: string;
    };

const ACTIVE_FORM_LOCALE: UiLocale = "zh";
const CM_PER_INCH = 2.54;
const GRAMS_PER_KG = 1000;
const GRAMS_PER_LB = 453.59237;
const GRAMS_PER_OZ = 28.349523125;

const TARGET_MARKETS: TargetMarketOption[] = [
  {
    code: "US",
    label: "United States",
    zhLabel: "美国",
    unitProfile: "US",
    contentLocale: "en",
    currency: "USD",
  },
  {
    code: "UK",
    label: "United Kingdom",
    zhLabel: "英国",
    unitProfile: "UK",
    contentLocale: "en",
    currency: "GBP",
  },
  {
    code: "EU",
    label: "EU",
    zhLabel: "欧盟",
    unitProfile: "EU",
    contentLocale: "en",
    currency: "EUR",
  },
  {
    code: "DE",
    label: "Germany",
    zhLabel: "德国",
    unitProfile: "EU",
    contentLocale: "de",
    currency: "EUR",
  },
  {
    code: "FR",
    label: "France",
    zhLabel: "法国",
    unitProfile: "EU",
    contentLocale: "fr",
    currency: "EUR",
  },
  {
    code: "IT",
    label: "Italy",
    zhLabel: "意大利",
    unitProfile: "EU",
    contentLocale: "it",
    currency: "EUR",
  },
  {
    code: "ES",
    label: "Spain",
    zhLabel: "西班牙",
    unitProfile: "EU",
    contentLocale: "es",
    currency: "EUR",
  },
  {
    code: "NL",
    label: "Netherlands",
    zhLabel: "荷兰",
    unitProfile: "EU",
    contentLocale: "nl",
    currency: "EUR",
  },
  {
    code: "RU",
    label: "Russia",
    zhLabel: "俄罗斯",
    unitProfile: "METRIC",
    contentLocale: "ru",
    currency: "RUB",
  },
  {
    code: "CN",
    label: "China",
    zhLabel: "中国",
    unitProfile: "CN",
    contentLocale: "zh-hans",
    currency: "CNY",
  },
  {
    code: "HK",
    label: "Hong Kong",
    zhLabel: "香港",
    unitProfile: "CN",
    contentLocale: "zh-hant",
    currency: "HKD",
  },
  {
    code: "MO",
    label: "Macau",
    zhLabel: "澳门",
    unitProfile: "CN",
    contentLocale: "zh-hant",
    currency: "MOP",
  },
  {
    code: "TW",
    label: "Taiwan",
    zhLabel: "台湾",
    unitProfile: "CN",
    contentLocale: "zh-hant",
    currency: "TWD",
  },
  {
    code: "JP",
    label: "Japan",
    zhLabel: "日本",
    unitProfile: "METRIC",
    contentLocale: "ja",
    currency: "JPY",
  },
  {
    code: "KR",
    label: "South Korea",
    zhLabel: "韩国",
    unitProfile: "METRIC",
    contentLocale: "ko",
    currency: "KRW",
  },
  {
    code: "BR",
    label: "Brazil",
    zhLabel: "巴西",
    unitProfile: "METRIC",
    contentLocale: "pt-br",
    currency: "BRL",
  },
  {
    code: "LATAM",
    label: "LATAM",
    zhLabel: "拉美",
    unitProfile: "METRIC",
    contentLocale: "es-419",
    currency: "USD",
  },
  {
    code: "MX",
    label: "Mexico",
    zhLabel: "墨西哥",
    unitProfile: "METRIC",
    contentLocale: "es-mx",
    currency: "MXN",
  },
  {
    code: "AR",
    label: "Argentina",
    zhLabel: "阿根廷",
    unitProfile: "METRIC",
    contentLocale: "es-ar",
    currency: "ARS",
  },
  {
    code: "GCC",
    label: "Middle East (GCC)",
    zhLabel: "中东 GCC",
    unitProfile: "METRIC",
    contentLocale: "ar",
    currency: "AED",
  },
];

const PRODUCT_FORM_LABELS = {
  zh: {
    brand: "品牌",
    category: "类目",
    addVariant: "添加变体",
    attributesJson: "属性 JSON",
    color: "颜色",
    create: "创建",
    createProduct: "创建产品",
    creating: "创建中",
    currency: "币种",
    description: "产品描述",
    descriptionPlaceholder: "粘贴产品描述、卖点或原始资料。",
    dimensions: "尺寸",
    dimensionsInvalid: "尺寸必须同时填写长、宽、高，并且必须为正数。",
    fieldRequired: "Parent SKU、产品描述和目标市场为必填项。",
    function: "功能",
    height: "高",
    length: "长",
    market: "目标市场",
    marketInvalid: "请选择有效的目标市场。",
    marketSearch: "市场搜索",
    marketSearchPlaceholder: "搜索国家或地区",
    name: "产品名称",
    newProduct: "新建产品",
    parentSku: "Parent SKU",
    price: "价格",
    priceOverride: "变体价格",
    priceInvalid: "价格必须为空或正数。",
    productInfo: "产品信息",
    productKeyAuto: "Product Key 由后端自动生成，创建后不可变。",
    productType: "产品类型",
    quantity: "库存数量",
    removeVariant: "删除",
    simpleProduct: "Simple Product",
    size: "尺码",
    sku: "SKU",
    targetMarketStatus: "DeepSeek 转换：创建后自动执行",
    unit: "单位",
    unitConversionHint: "保存时自动转换",
    variableProduct: "Variable Product",
    variantRequired: "Variable product 至少需要一个变体。",
    variants: "变体",
    variantSkuPreview: "Variant SKU 预览",
    weight: "重量",
    weightInvalid: "重量必须为空或正数。",
    weightValue: "重量值",
    width: "宽",
  },
  en: {
    brand: "Brand",
    category: "Category",
    addVariant: "Add Variant",
    attributesJson: "Attributes JSON",
    color: "Color",
    create: "Create",
    createProduct: "Create Product",
    creating: "Creating",
    currency: "Currency",
    description: "Product Description",
    descriptionPlaceholder: "Paste product description, selling points, or notes.",
    dimensions: "Dimensions",
    dimensionsInvalid:
      "Dimensions require length, width, and height as positive numbers.",
    fieldRequired:
      "Parent SKU, product description, and target market are required.",
    function: "Function",
    height: "Height",
    length: "Length",
    market: "Target Market",
    marketInvalid: "Choose a valid target market.",
    marketSearch: "Market Search",
    marketSearchPlaceholder: "Search country or region",
    name: "Product Name",
    newProduct: "New Product",
    parentSku: "Parent SKU",
    price: "Price",
    priceOverride: "Variant Price",
    priceInvalid: "Price must be empty or positive.",
    productInfo: "Product Information",
    productKeyAuto: "Product Key is generated by the backend and immutable.",
    productType: "Product Type",
    quantity: "Quantity",
    removeVariant: "Remove",
    simpleProduct: "Simple Product",
    size: "Size",
    sku: "SKU",
    targetMarketStatus: "DeepSeek conversion: automatic after create",
    unit: "Unit",
    unitConversionHint: "Auto-converted on save",
    variableProduct: "Variable Product",
    variantRequired: "Variable product requires at least one variant.",
    variants: "Variants",
    variantSkuPreview: "Variant SKU Preview",
    weight: "Weight",
    weightInvalid: "Weight must be empty or a positive number.",
    weightValue: "Weight Value",
    width: "Width",
  },
} satisfies Record<UiLocale, Record<string, string>>;

const initialValues: ProductFormValues = {
  brand_name: "",
  dimensions_input: {
    height: "",
    length: "",
    unit: "cm",
    width: "",
  },
  price_currency: "USD",
  price_value: "",
  product_name_en: "",
  product_type: "simple_product",
  raw_input_text: "",
  parent_sku: "",
  target_market: "US",
  variants: [
    {
      attributes_text: "",
      color: "",
      function: "",
      price_override: "",
      quantity: "",
      size: "",
    },
  ],
  weight_input: {
    unit: "kg",
    value: "",
  },
};

type ProductFormProps = {
  error: string;
  isSubmitting: boolean;
  onCreate: (payload: ProductCreateFormPayload) => Promise<void>;
  onDismissError: () => void;
};

function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function targetMarketForCode(code: string) {
  return TARGET_MARKETS.find((market) => market.code === code) ?? null;
}

function dimensionsUnitForMarket(
  market: TargetMarketOption,
): ProductDimensionsInput["unit"] {
  return market.unitProfile === "US" || market.unitProfile === "UK"
    ? "inch"
    : "cm";
}

function weightUnitForMarket(market: TargetMarketOption): ProductWeightInput["unit"] {
  if (market.unitProfile === "US" || market.unitProfile === "UK") {
    return "lb";
  }
  if (market.unitProfile === "CN") {
    return "g";
  }
  return "kg";
}

function unitConversionSummary(market: TargetMarketOption) {
  return `${market.code}: ${dimensionsUnitForMarket(market)} / ${weightUnitForMarket(market)}`;
}

function parsePositiveNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return { provided: false, value: null };
  }

  const parsed = Number(trimmed);
  return {
    provided: true,
    value: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
  };
}

function roundMeasurement(value: number) {
  return Number(value.toFixed(3));
}

function convertDimension(
  value: number,
  fromUnit: ProductDimensionsInput["unit"],
  toUnit: ProductDimensionsInput["unit"],
) {
  if (fromUnit === toUnit) {
    return value;
  }
  return fromUnit === "cm" ? value / CM_PER_INCH : value * CM_PER_INCH;
}

function convertWeight(
  value: number,
  fromUnit: ProductWeightInput["unit"],
  toUnit: ProductWeightInput["unit"],
) {
  const grams =
    fromUnit === "kg"
      ? value * GRAMS_PER_KG
      : fromUnit === "lb"
        ? value * GRAMS_PER_LB
        : fromUnit === "oz"
          ? value * GRAMS_PER_OZ
          : value;

  if (toUnit === "kg") {
    return grams / GRAMS_PER_KG;
  }
  if (toUnit === "lb") {
    return grams / GRAMS_PER_LB;
  }
  if (toUnit === "oz") {
    return grams / GRAMS_PER_OZ;
  }
  return grams;
}

function normalizeDimensionsInput(
  input: ProductDimensionsInput,
  market: TargetMarketOption,
  labels: (typeof PRODUCT_FORM_LABELS)[UiLocale],
): FieldResult<NormalizedDimensions> {
  const length = parsePositiveNumber(input.length);
  const width = parsePositiveNumber(input.width);
  const height = parsePositiveNumber(input.height);
  const values = [length, width, height];

  if (values.every((item) => !item.provided)) {
    return { ok: true, value: null };
  }
  if (values.some((item) => !item.provided || item.value === null)) {
    return { ok: false, message: labels.dimensionsInvalid };
  }

  const targetUnit = dimensionsUnitForMarket(market);
  const source = {
    height: height.value as number,
    length: length.value as number,
    unit: input.unit,
    width: width.value as number,
  };

  return {
    ok: true,
    value: {
      height: roundMeasurement(convertDimension(source.height, input.unit, targetUnit)),
      length: roundMeasurement(convertDimension(source.length, input.unit, targetUnit)),
      source,
      target_market: market.code,
      target_market_label: market.label,
      unit: targetUnit,
      width: roundMeasurement(convertDimension(source.width, input.unit, targetUnit)),
    },
  };
}

function normalizeWeightInput(
  input: ProductWeightInput,
  market: TargetMarketOption,
  labels: (typeof PRODUCT_FORM_LABELS)[UiLocale],
): FieldResult<NormalizedWeight> {
  const parsed = parsePositiveNumber(input.value);

  if (!parsed.provided) {
    return { ok: true, value: null };
  }
  if (parsed.value === null) {
    return { ok: false, message: labels.weightInvalid };
  }

  const targetUnit = weightUnitForMarket(market);
  return {
    ok: true,
    value: {
      source: {
        unit: input.unit,
        value: parsed.value,
      },
      target_market: market.code,
      target_market_label: market.label,
      unit: targetUnit,
      value: roundMeasurement(convertWeight(parsed.value, input.unit, targetUnit)),
    },
  };
}

function normalizePriceInput(
  value: string,
  currency: string,
  market: TargetMarketOption,
  labels: (typeof PRODUCT_FORM_LABELS)[UiLocale],
): FieldResult<NormalizedPrice> {
  const parsed = parsePositiveNumber(value);

  if (!parsed.provided) {
    return { ok: true, value: null };
  }
  if (parsed.value === null) {
    return { ok: false, message: labels.priceInvalid };
  }

  return {
    ok: true,
    value: {
      currency,
      target_market: market.code,
      target_market_label: market.label,
      value: parsed.value,
    },
  };
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }

  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}

function variantHash(seed: Record<string, unknown>) {
  const canonical = stableJson(seed);
  let value = 0x811c9dc5;

  for (let index = 0; index < canonical.length; index += 1) {
    value ^= canonical.charCodeAt(index);
    value = Math.imul(value, 0x01000193) >>> 0;
  }

  return value.toString(16).toUpperCase().padStart(8, "0");
}

function normalizeSku(value: string) {
  return value.trim().replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "").toUpperCase();
}

function parseOptionalInteger(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

function parseOptionalPrice(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseVariantAttributes(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  return parsed && typeof parsed === "object" && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : {};
}

function variantSeed(variant: ProductVariantFormInput, index: number) {
  let attributes: Record<string, unknown> = {};
  try {
    attributes = parseVariantAttributes(variant.attributes_text);
  } catch {
    attributes = {};
  }

  return {
    attributes,
    color: optionalText(variant.color),
    function: optionalText(variant.function),
    index,
    size: optionalText(variant.size),
  };
}

function variantSkuPreview(parentSku: string, variant: ProductVariantFormInput, index: number) {
  const normalizedParentSku = normalizeSku(parentSku);
  if (!normalizedParentSku) {
    return "";
  }
  return `${normalizedParentSku}-${variantHash(variantSeed(variant, index))}`;
}

function buildVariantPayloads(
  parentSku: string,
  variants: ProductVariantFormInput[],
): ProductVariantInput[] {
  if (!normalizeSku(parentSku)) {
    return [];
  }

  return variants.map((variant) => ({
    attributes: parseVariantAttributes(variant.attributes_text),
    color: optionalText(variant.color),
    function: optionalText(variant.function),
    price_override: parseOptionalPrice(variant.price_override),
    quantity: parseOptionalInteger(variant.quantity),
    size: optionalText(variant.size),
  }));
}

function buildMultilingualFields(
  values: ProductFormValues,
  market: TargetMarketOption,
) {
  return {
    localized_fields: {
      [market.contentLocale]: {
        description: values.raw_input_text.trim(),
        product_name: optionalText(values.product_name_en),
      },
    },
    provider: "deepseek",
    source: {
      description: values.raw_input_text.trim(),
      product_name: optionalText(values.product_name_en),
    },
    status: "queued_after_product_create",
    target_market: {
      code: market.code,
      label: market.label,
      locale: market.contentLocale,
    },
  };
}

function buildAttributes({
  dimensions,
  market,
  multilingualFields,
  price,
  weight,
}: {
  dimensions: NormalizedDimensions | null;
  market: TargetMarketOption;
  multilingualFields: Record<string, unknown>;
  price: NormalizedPrice | null;
  weight: NormalizedWeight | null;
}): ProductKnowledgeAttributeInput[] {
  const attributes: ProductKnowledgeAttributeInput[] = [
    {
      attribute_group: "market",
      attribute_key: "target_market",
      attribute_value_json: {
        code: market.code,
        label: market.label,
        locale: market.contentLocale,
        unit_profile: market.unitProfile,
      },
      source: "frontend_product_form",
    },
    {
      attribute_group: "localization",
      attribute_key: "multilingual_fields",
      attribute_value_json: multilingualFields,
      source: "frontend_product_form",
    },
  ];

  if (price) {
    attributes.push({
      attribute_group: "commerce",
      attribute_key: "price",
      attribute_unit: price.currency,
      attribute_value_json: price,
      source: "frontend_product_form",
    });
  }

  if (dimensions) {
    attributes.push({
      attribute_group: "physical",
      attribute_key: "dimensions",
      attribute_unit: dimensions.unit,
      attribute_value_json: dimensions,
      source: "frontend_product_form",
    });
  }

  if (weight) {
    attributes.push({
      attribute_group: "physical",
      attribute_key: "weight",
      attribute_unit: weight.unit,
      attribute_value_json: weight,
      source: "frontend_product_form",
    });
  }

  return attributes;
}

export function ProductForm({
  error,
  isSubmitting,
  onCreate,
  onDismissError,
}: ProductFormProps) {
  const labels = PRODUCT_FORM_LABELS[ACTIVE_FORM_LOCALE];
  const [values, setValues] = useState<ProductFormValues>(initialValues);
  const [marketSearch, setMarketSearch] = useState("");
  const [validationError, setValidationError] = useState("");

  const selectedMarket = targetMarketForCode(values.target_market) ?? TARGET_MARKETS[0];
  const visibleTargetMarkets = useMemo(() => {
    const search = marketSearch.trim().toLowerCase();
    const filtered =
      search.length === 0
        ? TARGET_MARKETS
        : TARGET_MARKETS.filter((market) => {
            return (
              market.code.toLowerCase().includes(search) ||
              market.label.toLowerCase().includes(search) ||
              market.zhLabel.toLowerCase().includes(search)
            );
          });

    if (filtered.some((market) => market.code === selectedMarket.code)) {
      return filtered;
    }

    return [selectedMarket, ...filtered];
  }, [marketSearch, selectedMarket]);

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
    setMarketSearch("");
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

  function updateVariantValue(
    index: number,
    key: keyof ProductVariantFormInput,
    value: string,
  ) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index ? { ...variant, [key]: value } : variant,
      ),
    }));
    clearFormErrors();
  }

  function addVariant() {
    setValues((current) => ({
      ...current,
      product_type: "variable_product",
      variants: [
        ...current.variants,
        {
          attributes_text: "",
          color: "",
          function: "",
          price_override: "",
          quantity: "",
          size: "",
        },
      ],
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

    const parentSku = normalizeSku(values.parent_sku);
    const rawInputText = values.raw_input_text.trim();
    const market = targetMarketForCode(values.target_market);

    if (!market) {
      setValidationError(labels.marketInvalid);
      return;
    }
    if (!parentSku || !rawInputText || !values.target_market) {
      setValidationError(labels.fieldRequired);
      return;
    }
    if (values.product_type === "variable_product" && values.variants.length === 0) {
      setValidationError(labels.variantRequired);
      return;
    }

    const dimensions = normalizeDimensionsInput(
      values.dimensions_input,
      market,
      labels,
    );
    if (!dimensions.ok) {
      setValidationError(dimensions.message);
      return;
    }

    const weight = normalizeWeightInput(values.weight_input, market, labels);
    if (!weight.ok) {
      setValidationError(weight.message);
      return;
    }

    const price = normalizePriceInput(
      values.price_value,
      values.price_currency,
      market,
      labels,
    );
    if (!price.ok) {
      setValidationError(price.message);
      return;
    }

    let variants: ProductVariantInput[] = [];
    try {
      variants =
        values.product_type === "variable_product"
          ? buildVariantPayloads(parentSku, values.variants)
          : [];
    } catch {
      setValidationError(labels.attributesJson);
      return;
    }

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
        parent_sku: parentSku,
        product_type: values.product_type,
        variant_sku_rule: "variant_sku = parent_sku + '-' + variant_hash",
        variants:
          values.product_type === "variable_product"
            ? values.variants.map((variant, index) => ({
                preview_variant_sku: variantSkuPreview(parentSku, variant, index),
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
      parent_sku: parentSku,
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
          ? values.variants.map((variant, index) => ({
              ...variant,
              preview_variant_sku: variantSkuPreview(parentSku, variant, index),
            }))
          : [],
      weight_input: weight.value,
    };

    try {
      await onCreate({
        attributes,
        brand_name: optionalText(values.brand_name),
        dimensions_json: dimensions.value,
        long_description_en: rawInputText,
        manual_notes: JSON.stringify(frontendSchemaSnapshot, null, 2),
        parent_sku: parentSku,
        price_currency: price.value?.currency ?? values.price_currency,
        product_name_en: optionalText(values.product_name_en),
        product_status: "draft",
        product_type: values.product_type,
        regular_price: price.value?.value ?? null,
        raw_input_text: rawInputText,
        review_status: "draft",
        short_description_en: rawInputText,
        sku: parentSku,
        source_system: "manual",
        target_locale: market.contentLocale,
        target_market: market.code,
        target_market_label: market.label,
        variants,
        weight_json: weight.value,
      });
      setValues(initialValues);
      setMarketSearch("");
    } catch {
      // The parent renders the API error; keep the entered values for retry.
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
        <button
          className="primary-button"
          disabled={isSubmitting}
          type="submit"
        >
          {isSubmitting ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          {isSubmitting ? labels.creating : labels.createProduct}
        </button>
      </div>

      <section className={styles.formSection} aria-labelledby="k-product-info">
        <div className={styles.formSectionHeading}>
          <h4 id="k-product-info">{labels.productInfo}</h4>
        </div>

        <div className={styles.formGrid}>
          <div className={styles.autoKeyNotice}>
            <strong>Product Key</strong>
            <span>{labels.productKeyAuto}</span>
          </div>

          <label className={styles.field}>
            <span>{labels.name}</span>
            <input
              autoComplete="off"
              onChange={(event) =>
                updateValue("product_name_en", event.target.value)
              }
              placeholder="Stainless steel pump"
              value={values.product_name_en}
            />
          </label>

          <label className={styles.field}>
            <span>{labels.parentSku}</span>
            <input
              autoComplete="off"
              onChange={(event) => updateValue("parent_sku", event.target.value)}
              placeholder="SKU-1001"
              required
              value={values.parent_sku}
            />
          </label>

          <label className={styles.field}>
            <span>{labels.brand}</span>
            <input
              autoComplete="off"
              onChange={(event) =>
                updateValue("brand_name", event.target.value)
              }
              placeholder="Brand"
              value={values.brand_name}
            />
          </label>

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

          <div className={styles.inlineFields}>
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

      <section className={styles.formSection} aria-labelledby="k-target-market">
        <div className={styles.formSectionHeading}>
          <Globe2 aria-hidden="true" size={18} />
          <h4 id="k-target-market">{labels.market}</h4>
          <span>{labels.targetMarketStatus}</span>
        </div>

        <div className={styles.formGrid}>
          <label className={styles.field}>
            <span>{labels.marketSearch}</span>
            <input
              autoComplete="off"
              onChange={(event) => setMarketSearch(event.target.value)}
              placeholder={labels.marketSearchPlaceholder}
              value={marketSearch}
            />
          </label>

          <label className={styles.field}>
            <span>{labels.market}</span>
            <select
              onChange={(event) => updateMarket(event.target.value)}
              required
              value={values.target_market}
            >
              {visibleTargetMarkets.map((market) => (
                <option key={market.code} value={market.code}>
                  {market.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

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

      {values.product_type === "variable_product" ? (
        <section className={styles.formSection} aria-labelledby="k-variants">
          <div className={styles.formSectionHeading}>
            <h4 id="k-variants">{labels.variants}</h4>
            <button className="secondary-button" onClick={addVariant} type="button">
              <Plus aria-hidden="true" size={15} />
              {labels.addVariant}
            </button>
          </div>

          <div className={styles.variantEditor}>
            {values.variants.map((variant, index) => {
              const preview = variantSkuPreview(values.parent_sku, variant, index);

              return (
                <section className={styles.variantRow} key={index}>
                  <div className={styles.variantPreview}>
                    <strong>{labels.variantSkuPreview}</strong>
                    <span>{preview || `${labels.parentSku} + variant_hash`}</span>
                    <button
                      className="secondary-button"
                      disabled={values.variants.length <= 1}
                      onClick={() => removeVariant(index)}
                      type="button"
                    >
                      {labels.removeVariant}
                    </button>
                  </div>

                  <div className={styles.variantGrid}>
                    <label className={styles.field}>
                      <span>{labels.color}</span>
                      <input
                        onChange={(event) =>
                          updateVariantValue(index, "color", event.target.value)
                        }
                        value={variant.color}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.size}</span>
                      <input
                        onChange={(event) =>
                          updateVariantValue(index, "size", event.target.value)
                        }
                        value={variant.size}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.function}</span>
                      <input
                        onChange={(event) =>
                          updateVariantValue(index, "function", event.target.value)
                        }
                        value={variant.function}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.quantity}</span>
                      <input
                        inputMode="numeric"
                        onChange={(event) =>
                          updateVariantValue(index, "quantity", event.target.value)
                        }
                        value={variant.quantity}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.priceOverride}</span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantValue(
                            index,
                            "price_override",
                            event.target.value,
                          )
                        }
                        value={variant.price_override}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{labels.attributesJson}</span>
                      <input
                        onChange={(event) =>
                          updateVariantValue(
                            index,
                            "attributes_text",
                            event.target.value,
                          )
                        }
                        placeholder='{"material":"steel"}'
                        value={variant.attributes_text}
                      />
                    </label>
                  </div>
                </section>
              );
            })}
          </div>
        </section>
      ) : null}

      <label className={styles.field}>
        <span>{labels.description}</span>
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
    </form>
  );
}
