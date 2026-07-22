"use client";

import { Globe2, LoaderCircle, Plus, Ruler, Scale } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { searchCategories, type CategoryTreeItem } from "./api";

import styles from "./ProductKnowledge.module.css";
import {
  formatVariantAttributes,
  normalizeVariantAttributes,
} from "./display";
import type {
  ProductDimensionsInput,
  ProductCreateFormPayload,
  ProductFormValues,
  ProductKnowledgeAttributeInput,
  ProductManualSpecInput,
  ProductVariantAttributeInput,
  ProductVariantAttributeType,
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
const VARIANT_ATTRIBUTE_TYPES: ProductVariantAttributeType[] = [
  "size",
  "color",
  "function",
  "quantity",
];

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
    addAttribute: "添加到当前变体",
    addVariant: "添加变体",
    attributeType: "属性类型",
    attributeValue: "属性值",
    color: "颜色",
    create: "创建",
    createProduct: "创建产品",
    creating: "创建中",
    currency: "币种",
    description: "产品描述",
    descriptionPlaceholder: "粘贴产品描述、卖点或原始资料。",
    dimensions: "尺寸",
    dimensionsInvalid: "尺寸必须同时填写长、宽、高，并且必须为正数。",
    fieldRequired: "父级 SKU、主关键词、产品描述和目标市场为必填项。",
    function: "功能",
    height: "高",
    length: "长",
    market: "目标市场",
    marketInvalid: "请选择有效的目标市场。",
    mainKeyword: "主关键词",
    mainKeywordPlaceholder: "例如 stainless steel pump",
    name: "产品名称",
    newProduct: "新建产品",
    parentSku: "Parent SKU",
    price: "价格",
    priceOverride: "变体价格",
    priceInvalid: "价格必须为空或正数。",
    productInfo: "产品信息",
    productKeyAuto: "产品键由后端自动生成，创建后不可变。",
    productType: "产品类型",
    quantity: "库存数量",
    removeVariant: "删除",
    simpleProduct: "单产品",
    size: "尺码",
    sku: "SKU",
    targetMarketStatus: "DeepSeek 转换：创建后自动执行",
    unit: "单位",
    unitConversionHint: "保存时自动转换",
    variableProduct: "多变体产品",
    variantAttributesRequired: "每个变体至少需要一个属性。",
    variantDisplay: "变体名称",
    variantDuplicateAttributeTypes: "同一个变体内同一种属性只能填写一次；需要多个颜色、尺码或功能时，请点击“添加变体”分别录入。",
    variantEditorHint: "每个变体卡片会保存为一条独立后端变体。需要多个图片绑定目标时，请点击“添加变体”分别录入，不要把多个变体写进同一张卡片。",
    variantNameEmpty: "点击添加属性生成变体名称",
    variantRowLabel: "变体",
    variantRequired: "多变体产品至少需要一个变体。",
    variants: "变体",
    weight: "重量",
    weightInvalid: "重量必须为空或正数。",
    weightValue: "重量值",
    width: "宽",
  },
  en: {
    brand: "品牌",
    category: "类目",
    addAttribute: "添加到当前变体",
    addVariant: "添加变体",
    attributeType: "属性类型",
    attributeValue: "属性值",
    color: "颜色",
    create: "创建",
    createProduct: "创建产品",
    creating: "创建中",
    currency: "币种",
    description: "产品描述",
    descriptionPlaceholder: "粘贴产品描述、卖点或原始资料。",
    dimensions: "尺寸",
    dimensionsInvalid: "尺寸必须同时填写长、宽、高，并且必须为正数。",
    fieldRequired: "父级 SKU、主关键词、产品描述和目标市场为必填项。",
    function: "功能",
    height: "高",
    length: "长",
    market: "目标市场",
    marketInvalid: "请选择有效的目标市场。",
    mainKeyword: "主关键词",
    mainKeywordPlaceholder: "例如 stainless steel pump",
    name: "产品名称",
    newProduct: "新建产品",
    parentSku: "父级 SKU",
    price: "价格",
    priceOverride: "变体价格",
    priceInvalid: "价格必须为空或正数。",
    productInfo: "产品信息",
    productKeyAuto: "产品键由后端自动生成，创建后不可变。",
    productType: "产品类型",
    quantity: "库存数量",
    removeVariant: "删除",
    simpleProduct: "单产品",
    size: "尺码",
    sku: "SKU",
    targetMarketStatus: "DeepSeek 转换：创建后自动执行",
    unit: "单位",
    unitConversionHint: "保存时自动转换",
    variableProduct: "多变体产品",
    variantAttributesRequired: "每个变体至少需要一个属性。",
    variantDisplay: "变体名称",
    variantDuplicateAttributeTypes: "同一个变体内同一种属性只能填写一次；需要多个颜色、尺码或功能时，请点击“添加变体”分别录入。",
    variantEditorHint: "每个变体卡片会保存为一条独立后端变体。需要多个图片绑定目标时，请点击“添加变体”分别录入，不要把多个变体写进同一张卡片。",
    variantNameEmpty: "点击添加属性生成变体名称",
    variantRowLabel: "变体",
    variantRequired: "多变体产品至少需要一个变体。",
    variants: "变体",
    weight: "重量",
    weightInvalid: "重量必须为空或正数。",
    weightValue: "重量值",
    width: "宽",
  },
} satisfies Record<UiLocale, Record<string, string>>;

const initialValues: ProductFormValues = {
  brand_name: "",
  source_url: "",
  reference_image_url: "",
  dimensions_input: {
    height: "",
    length: "",
    unit: "cm",
    width: "",
  },
  price_currency: "USD",
  price_value: "",
  product_name_en: "",
  main_keyword: "",
  product_type: "simple_product",
  raw_input_text: "",
  target_market: "US",
  channel: "dtc",
  category_id: "",
  category_label: "",
  variants: [
    {
      price_override: "",
      attributes: [],
    },
  ],
  weight_input: {
    unit: "kg",
    value: "",
  },
  package_includes: [""],
  manual_specs: [{ label: "", value: "", unit: "" }],
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

function hasDuplicateVariantAttributeTypes(variant: ProductVariantFormInput) {
  const seen = new Set<ProductVariantAttributeType>();

  for (const attribute of normalizeVariantAttributes(variant.attributes)) {
    if (seen.has(attribute.type)) {
      return true;
    }
    seen.add(attribute.type);
  }

  return false;
}

function attributePlaceholder(type: ProductVariantAttributeType) {
  if (type === "color") {
    return "黄色";
  }
  if (type === "size") {
    return "S";
  }
  if (type === "function") {
    return "标准";
  }
  return "12";
}

function variantAttributeTypeLabel(type: ProductVariantAttributeType) {
  const labels: Record<ProductVariantAttributeType, string> = {
    color: "颜色",
    function: "功能",
    quantity: "库存数量",
    size: "尺码",
  };

  return labels[type];
}

function buildVariantPayloads(
  variants: ProductVariantFormInput[],
): ProductVariantInput[] {
  return variants.map((variant) => {
    const attributes = normalizeVariantAttributes(variant.attributes);
    const firstValueFor = (type: ProductVariantAttributeType) =>
      attributes.find((attribute) => attribute.type === type)?.value ?? "";

    return {
      attributes: {
        attribute_schema: "attribute_builder_v1",
        display_name: formatVariantAttributes(attributes),
        variant_attributes: attributes,
      },
      color: optionalText(firstValueFor("color")),
      function: optionalText(firstValueFor("function")),
      price_override: parseOptionalPrice(variant.price_override),
      quantity: parseOptionalInteger(firstValueFor("quantity")),
      size: optionalText(firstValueFor("size")),
    };
  });
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

  function updateVariantPrice(index: number, value: string) {
    setValues((current) => ({
      ...current,
      variants: current.variants.map((variant, variantIndex) =>
        variantIndex === index ? { ...variant, price_override: value } : variant,
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
      variants: [
        ...current.variants,
        {
          price_override: "",
          attributes: [],
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
    const refImageUrl = values.reference_image_url.trim();
    if (refImageUrl && !/^https?:\/\//i.test(refImageUrl)) {
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

    const variants =
      values.product_type === "variable_product"
        ? buildVariantPayloads(values.variants)
        : [];

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
        reference_image_url: optionalText(values.reference_image_url),
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
      setValues(initialValues);
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

          <label className={styles.field}>
            <span>参考图链接（可选）</span>
            <input
              autoComplete="off"
              inputMode="url"
              onChange={(event) =>
                updateValue("reference_image_url", event.target.value)
              }
              placeholder="1688 主图右键「复制图片地址」贴这里，直接喂渲染管线"
              value={values.reference_image_url}
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
                  color: "var(--mm-cyan, #39d4ff)",
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
                  border: "1px solid var(--mm-line, rgba(120,200,255,0.18))",
                  borderRadius: 8,
                  background: "rgba(6,12,20,0.6)",
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
                      <span>{labels.priceOverride}</span>
                      <input
                        inputMode="decimal"
                        onChange={(event) =>
                          updateVariantPrice(index, event.target.value)
                        }
                        value={variant.price_override}
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
