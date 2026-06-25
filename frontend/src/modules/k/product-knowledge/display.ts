import type {
  ProductKnowledgeVariant,
  ProductVariantAttributeInput,
  ProductVariantAttributeType,
} from "./types";

const ATTRIBUTE_ORDER: ProductVariantAttributeType[] = [
  "color",
  "size",
  "function",
  "quantity",
];

const COLOR_LABELS: Record<string, string> = {
  black: "黑色",
  blue: "蓝色",
  brown: "棕色",
  gray: "灰色",
  green: "绿色",
  grey: "灰色",
  orange: "橙色",
  pink: "粉色",
  purple: "紫色",
  red: "红色",
  white: "白色",
  yellow: "黄色",
};

export function displayProductKey(productKey: string | null | undefined) {
  const compact = (productKey ?? "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (!compact) {
    return "PRODUCT-NEW";
  }

  const prefix = compact.slice(0, 4).padEnd(4, "0");
  const suffix = compact.slice(-4).padStart(4, "0");
  return `PRODUCT-${prefix}-${suffix}`;
}

export function formatVariantAttributeValue(
  type: ProductVariantAttributeType,
  value: string,
) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  if (type === "color") {
    return COLOR_LABELS[trimmed.toLowerCase()] ?? trimmed;
  }
  if (type === "size") {
    return /码$|size/i.test(trimmed) ? trimmed : `${trimmed}码`;
  }
  if (type === "quantity") {
    return /件$|pcs?$/i.test(trimmed) ? trimmed : `${trimmed}件`;
  }
  return trimmed;
}

export function normalizeVariantAttributes(
  attributes: ProductVariantAttributeInput[],
) {
  return attributes
    .map((attribute) => ({
      type: attribute.type,
      value: attribute.value.trim(),
    }))
    .filter((attribute) => attribute.value.length > 0);
}

export function formatVariantAttributes(
  attributes: ProductVariantAttributeInput[],
) {
  const normalized = normalizeVariantAttributes(attributes);
  return ATTRIBUTE_ORDER.flatMap((type) =>
    normalized
      .filter((attribute) => attribute.type === type)
      .map((attribute) => formatVariantAttributeValue(type, attribute.value)),
  )
    .filter(Boolean)
    .join(" | ");
}

function readString(value: unknown) {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function readAttributePair(value: unknown): ProductVariantAttributeInput | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const type = readString(record.type);
  const attributeValue = readString(record.value);
  if (
    !attributeValue ||
    (type !== "size" &&
      type !== "color" &&
      type !== "function" &&
      type !== "quantity")
  ) {
    return null;
  }

  return {
    type,
    value: attributeValue,
  };
}

function attributesFromJson(value: unknown): ProductVariantAttributeInput[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }

  const record = value as Record<string, unknown>;
  const candidateList = Array.isArray(record.variant_attributes)
    ? record.variant_attributes
    : Array.isArray(record.attributes)
      ? record.attributes
      : [];
  const structured = candidateList
    .map((item) => readAttributePair(item))
    .filter((item): item is ProductVariantAttributeInput => item !== null);
  if (structured.length > 0) {
    return structured;
  }

  return ATTRIBUTE_ORDER.flatMap((type) => {
    const valueForType = readString(record[type]);
    return valueForType ? [{ type, value: valueForType }] : [];
  });
}

export function formatVariantDisplayName(
  variant: Pick<
    ProductKnowledgeVariant,
    | "attributes_json"
    | "color"
    | "function"
    | "quantity"
    | "size"
    | "variant_sku"
  >,
) {
  const attributes = attributesFromJson(variant.attributes_json);
  const fallbackAttributes: ProductVariantAttributeInput[] = [
    variant.color ? { type: "color", value: variant.color } : null,
    variant.size ? { type: "size", value: variant.size } : null,
    variant.function ? { type: "function", value: variant.function } : null,
    variant.quantity !== null && variant.quantity !== undefined
      ? { type: "quantity", value: String(variant.quantity) }
      : null,
  ].filter((item): item is ProductVariantAttributeInput => item !== null);

  return (
    formatVariantAttributes(attributes.length > 0 ? attributes : fallbackAttributes) ||
    "默认变体 / Default"
  );
}

export function mediaVariantDisplayName(
  variants: ProductKnowledgeVariant[] | undefined,
  variantSku: string | null | undefined,
) {
  if (!variantSku) {
    return "未绑定变体 / No variant";
  }

  const variant = (variants ?? []).find((item) => item.variant_sku === variantSku);
  return variant ? formatVariantDisplayName(variant) : "变体已删除 / Variant removed";
}
