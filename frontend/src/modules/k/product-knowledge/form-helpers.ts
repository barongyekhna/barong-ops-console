// 建品表单的纯函数与常量。2026-09-04 从 ProductForm.tsx 原样搬出(只加 export,
// 内容一字不改),让「基础档案」面板与新建表单共用同一套单位换算、校验和变体装配。

import {
  formatVariantAttributes,
  normalizeVariantAttributes,
  variantAttributesFromJson,
} from "./display";
import type {
  ProductDimensionsInput,
  ProductCreateFormPayload,
  ProductFormValues,
  ProductKnowledgeAttributeInput,
  ProductVariantAttributeType,
  ProductVariantFormInput,
  ProductVariantInput,
  ProductWeightInput,
  ProductKnowledgeVariant,
  ProductVariantAttributeInput,
} from "./types";

export type UiLocale = "zh" | "en";
export type UnitProfile = "US" | "UK" | "EU" | "CN" | "METRIC";
export type StringProductFormField = {
  [Key in keyof ProductFormValues]: ProductFormValues[Key] extends string
    ? Key
    : never;
}[keyof ProductFormValues];

export type TargetMarketOption = {
  code: string;
  label: string;
  zhLabel: string;
  unitProfile: UnitProfile;
  contentLocale: string;
  currency: string;
};

export type NormalizedDimensions = {
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

export type NormalizedWeight = {
  value: number;
  unit: ProductWeightInput["unit"];
  source: {
    value: number;
    unit: ProductWeightInput["unit"];
  };
  target_market: string;
  target_market_label: string;
};

export type NormalizedPrice = {
  value: number;
  currency: string;
  target_market: string;
  target_market_label: string;
};

export type FieldResult<T> =
  | {
      ok: true;
      value: T | null;
    }
  | {
      ok: false;
      message: string;
    };

export const ACTIVE_FORM_LOCALE: UiLocale = "zh";
export const CM_PER_INCH = 2.54;
export const GRAMS_PER_KG = 1000;
export const GRAMS_PER_LB = 453.59237;
export const GRAMS_PER_OZ = 28.349523125;
export const VARIANT_ATTRIBUTE_TYPES: ProductVariantAttributeType[] = [
  "size",
  "color",
  "function",
  "quantity",
];

export const TARGET_MARKETS: TargetMarketOption[] = [
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

export const PRODUCT_FORM_LABELS = {
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
    variantEditorHint: "每个变体卡片会保存为一条独立后端变体。价格必填；尺寸重量按变体分别填写（如 1 个装 / 2 个装不同）。需要多个图片绑定目标时，请点击“添加变体”分别录入。",
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
    variantEditorHint: "每个变体卡片会保存为一条独立后端变体。价格必填；尺寸重量按变体分别填写（如 1 个装 / 2 个装不同）。需要多个图片绑定目标时，请点击“添加变体”分别录入。",
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

export function emptyVariantInput(): ProductVariantFormInput {
  return {
    price_override: "",
    attributes: [],
    dimensions_input: {
      height: "",
      length: "",
      unit: "cm",
      width: "",
    },
    weight_input: {
      unit: "kg",
      value: "",
    },
    reference_image_url: "",
  };
}

export function makeInitialValues(): ProductFormValues {
  return {
    brand_name: "",
    source_url: "",
    reference_image_urls: [""],
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
    extra_keywords: [""],
    product_type: "simple_product",
    raw_input_text: "",
    target_market: "US",
    channel: "dtc",
    category_id: "",
    category_label: "",
    festival_style: "",
    variants: [emptyVariantInput()],
    weight_input: {
      unit: "kg",
      value: "",
    },
    package_includes: [""],
    manual_specs: [{ label: "", value: "", unit: "" }],
  };
}

export type ProductFormProps = {
  error: string;
  isSubmitting: boolean;
  onCreate: (payload: ProductCreateFormPayload) => Promise<void>;
  onDismissError: () => void;
};

export function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function targetMarketForCode(code: string) {
  return TARGET_MARKETS.find((market) => market.code === code) ?? null;
}

export function dimensionsUnitForMarket(
  market: TargetMarketOption,
): ProductDimensionsInput["unit"] {
  return market.unitProfile === "US" || market.unitProfile === "UK"
    ? "inch"
    : "cm";
}

export function weightUnitForMarket(market: TargetMarketOption): ProductWeightInput["unit"] {
  if (market.unitProfile === "US" || market.unitProfile === "UK") {
    return "lb";
  }
  if (market.unitProfile === "CN") {
    return "g";
  }
  return "kg";
}

export function unitConversionSummary(market: TargetMarketOption) {
  return `${market.code}: ${dimensionsUnitForMarket(market)} / ${weightUnitForMarket(market)}`;
}

export function parsePositiveNumber(value: string) {
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

export function roundMeasurement(value: number) {
  return Number(value.toFixed(3));
}

export function convertDimension(
  value: number,
  fromUnit: ProductDimensionsInput["unit"],
  toUnit: ProductDimensionsInput["unit"],
) {
  if (fromUnit === toUnit) {
    return value;
  }
  return fromUnit === "cm" ? value / CM_PER_INCH : value * CM_PER_INCH;
}

export function convertWeight(
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

export function normalizeDimensionsInput(
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

export function normalizeWeightInput(
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

export function normalizePriceInput(
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

export function parseOptionalInteger(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

export function parseOptionalPrice(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function hasDuplicateVariantAttributeTypes(variant: ProductVariantFormInput) {
  const seen = new Set<ProductVariantAttributeType>();

  for (const attribute of normalizeVariantAttributes(variant.attributes)) {
    if (seen.has(attribute.type)) {
      return true;
    }
    seen.add(attribute.type);
  }

  return false;
}

export function attributePlaceholder(type: ProductVariantAttributeType) {
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

export function variantAttributeTypeLabel(type: ProductVariantAttributeType) {
  const labels: Record<ProductVariantAttributeType, string> = {
    color: "颜色",
    function: "功能",
    quantity: "库存数量",
    size: "尺码",
  };

  return labels[type];
}

export function buildVariantPayloads(
  variants: ProductVariantFormInput[],
  market: TargetMarketOption,
  labels: (typeof PRODUCT_FORM_LABELS)[UiLocale],
):
  | { ok: true; value: ProductVariantInput[] }
  | { ok: false; message: string } {
  const out: ProductVariantInput[] = [];

  for (const [index, variant] of variants.entries()) {
    const attributes = normalizeVariantAttributes(variant.attributes);
    const firstValueFor = (type: ProductVariantAttributeType) =>
      attributes.find((attribute) => attribute.type === type)?.value ?? "";

    const price = parseOptionalPrice(variant.price_override);
    if (price === null || price <= 0) {
      return {
        ok: false,
        message: `变体 ${index + 1}：每个变体都必须填写自己的价格（正数）。`,
      };
    }

    const dimensions = normalizeDimensionsInput(
      variant.dimensions_input,
      market,
      labels,
    );
    if (!dimensions.ok) {
      return { ok: false, message: `变体 ${index + 1}：${dimensions.message}` };
    }

    const weight = normalizeWeightInput(variant.weight_input, market, labels);
    if (!weight.ok) {
      return { ok: false, message: `变体 ${index + 1}：${weight.message}` };
    }

    const referenceUrl = variant.reference_image_url.trim();
    if (referenceUrl && !/^https?:\/\//i.test(referenceUrl)) {
      return {
        ok: false,
        message: `变体 ${index + 1}：参考图链接必须以 http:// 或 https:// 开头（可留空）。`,
      };
    }

    out.push({
      attributes: {
        attribute_schema: "attribute_builder_v1",
        display_name: formatVariantAttributes(attributes),
        variant_attributes: attributes,
      },
      color: optionalText(firstValueFor("color")),
      function: optionalText(firstValueFor("function")),
      price_override: price,
      quantity: parseOptionalInteger(firstValueFor("quantity")),
      size: optionalText(firstValueFor("size")),
      dimensions_json: dimensions.value,
      weight_json: weight.value,
      reference_image_url: referenceUrl || null,
    });
  }

  return { ok: true, value: out };
}

export function buildMultilingualFields(
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

export function buildAttributes({
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

// ---------------------------------------------------------------------------
// 「基础档案」面板(2026-09-04)用的回填函数:把读模型里的 JSON 变回表单输入。
// 建品表单只有「表单 → JSON」一个方向;建好之后再改就需要反方向。
// ---------------------------------------------------------------------------

/** 档案面板里的一行变体:表单输入 + 身份。variant_id 为 null = 保存时新建。 */
export type VariantDossierRow = ProductVariantFormInput & {
  variant_id: string | null;
  variant_sku: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function numberText(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return value.trim();
  }
  return "";
}

/**
 * dimensions_json → 表单输入。优先用 `source`(运营当初填的原值和单位),
 * 没有 source(别的路径写的 JSON)才用换算后的顶层值。
 */
export function dimensionsFormFromJson(
  value: unknown,
  defaultUnit: ProductDimensionsInput["unit"],
): ProductDimensionsInput {
  const record = isRecord(value) ? value : null;
  const source = record && isRecord(record.source) ? record.source : record;
  const unit = source?.unit;
  return {
    height: numberText(source?.height),
    length: numberText(source?.length),
    unit: unit === "cm" || unit === "inch" ? unit : defaultUnit,
    width: numberText(source?.width),
  };
}

/** weight_json → 表单输入。规则同上。 */
export function weightFormFromJson(
  value: unknown,
  defaultUnit: ProductWeightInput["unit"],
): ProductWeightInput {
  const record = isRecord(value) ? value : null;
  const source = record && isRecord(record.source) ? record.source : record;
  const unit = source?.unit;
  return {
    unit:
      unit === "kg" || unit === "lb" || unit === "g" || unit === "oz"
        ? unit
        : defaultUnit,
    value: numberText(source?.value),
  };
}

/**
 * 变体读模型 → 档案面板的一行。
 * 属性优先读 attributes_json.variant_attributes(建品表单写的),
 * 没有(F/R 搬进来的 default 行、老数据)就按列 color/size/function/quantity 拼;
 * 物理规格从 attributes_json.physical 回,参考图从 attributes_json.reference_image_url 回。
 */
export function variantFormFromRead(
  variant: ProductKnowledgeVariant,
  units: {
    dimensions: ProductDimensionsInput["unit"];
    weight: ProductWeightInput["unit"];
  },
): VariantDossierRow {
  const attrs = isRecord(variant.attributes_json) ? variant.attributes_json : {};
  let attributes = variantAttributesFromJson(attrs);
  if (attributes.length === 0) {
    const fromColumns: ProductVariantAttributeInput[] = [];
    if (variant.color) fromColumns.push({ type: "color", value: variant.color });
    if (variant.size) fromColumns.push({ type: "size", value: variant.size });
    if (variant.function) fromColumns.push({ type: "function", value: variant.function });
    if (variant.quantity !== null && variant.quantity !== undefined) {
      fromColumns.push({ type: "quantity", value: String(variant.quantity) });
    }
    attributes = fromColumns;
  }
  const physical = isRecord(attrs.physical) ? attrs.physical : {};
  const referenceUrl = attrs.reference_image_url;
  return {
    attributes,
    dimensions_input: dimensionsFormFromJson(physical.dimensions, units.dimensions),
    price_override:
      variant.price_override === null || variant.price_override === undefined
        ? ""
        : String(variant.price_override),
    reference_image_url: typeof referenceUrl === "string" ? referenceUrl : "",
    variant_id: variant.id,
    variant_sku: variant.variant_sku,
    weight_input: weightFormFromJson(physical.weight, units.weight),
  };
}
