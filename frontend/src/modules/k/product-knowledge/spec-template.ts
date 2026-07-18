import type {
  CategorySpecField,
  CategorySpecFieldValueType,
  CategorySpecTemplate,
  SpecPasteParseResponse,
} from "./types";

export const STANDARD_SPEC_KEYS = new Set([
  "lumens",
  "color_temperature_k",
  "battery_type",
  "battery_capacity_mah",
  "charge_time_h",
  "runtime_h",
  "ip_rating",
  "dimensions",
  "weight",
  "material",
  "mount_type",
  "certifications",
]);

const ROOT_METADATA_KEYS = new Set([
  "schema_version",
  "source",
  "additional_specs",
  "package_includes",
  "package_includes_source",
  "buyer_translation",
]);

export type ProductSpecDraftOrigin = "empty" | "saved" | "ai" | "manual";

export type ProductSpecDraft = {
  key: string;
  target: "additional" | "standard";
  labelZh: string;
  labelEn: string;
  valueType: CategorySpecFieldValueType;
  unit: string;
  required: boolean;
  enumOptions: string[];
  hintZh: string;
  inputValue: string;
  normalizedValue: unknown;
  rawValue: string;
  sourceLabel: string;
  origin: ProductSpecDraftOrigin;
  fromTemplate: boolean;
  dirty: boolean;
  preserveSourceEvidence: boolean;
  originalNode?: Record<string, unknown>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function containsCjk(value: string) {
  return /[\u3400-\u9fff\uf900-\ufaff]/u.test(value);
}

export function formatSpecInputValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function inferValueType(value: unknown): CategorySpecFieldValueType {
  if (typeof value === "number") {
    return "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  return "text";
}

const DIMENSION_TO_CM: Record<string, number> = {
  cm: 1,
  m: 100,
  mm: 0.1,
};

function dimensionInputValue(
  node: Record<string, unknown>,
  preferredUnit: string,
) {
  const sourceUnit =
    cleanString(node.unit) ||
    ["length", "width", "height"].reduce((unit, axis) => {
      if (unit) return unit;
      const leaf = isRecord(node[axis]) ? node[axis] : undefined;
      return cleanString(leaf?.unit);
    }, "");
  const targetUnit = preferredUnit || sourceUnit;
  const sourceScale = DIMENSION_TO_CM[sourceUnit.toLowerCase()];
  const targetScale = DIMENSION_TO_CM[targetUnit.toLowerCase()];
  const values = ["length", "width", "height"].map((axis) => {
    const leaf = isRecord(node[axis]) ? node[axis] : undefined;
    const value = leaf?.value;
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return null;
    }
    const converted =
      sourceScale && targetScale ? (value * sourceScale) / targetScale : value;
    return Number.isInteger(converted)
      ? String(converted)
      : String(Number(converted.toFixed(6)));
  });
  if (values.every((value): value is string => value !== null)) {
    return values.join(" × ");
  }

  const rootValue = node.value_en ?? node.value;
  if (
    typeof rootValue === "string" ||
    typeof rootValue === "number" ||
    typeof rootValue === "boolean"
  ) {
    return formatSpecInputValue(rootValue);
  }
  return cleanString(node.raw_value);
}

function shouldPreserveSourceEvidence(
  node: Record<string, unknown> | undefined,
  inputValue: string,
) {
  if (!node) return false;
  const rawValue = cleanString(node.raw_value);
  const sourceLabel = cleanString(node.source_label);
  if (!rawValue || !sourceLabel) return false;
  return (
    containsCjk(rawValue) ||
    Boolean(cleanString(node.value_en)) ||
    rawValue !== inputValue.trim()
  );
}

function normalizedValueForNode(
  node: Record<string, unknown> | undefined,
  valueType: CategorySpecFieldValueType,
) {
  if (!node) {
    return undefined;
  }
  if (
    (valueType === "text" || valueType === "enum") &&
    cleanString(node.value_en)
  ) {
    return cleanString(node.value_en);
  }
  if (node.value !== undefined && node.value !== null) {
    return node.value;
  }
  // Composite standard fields such as dimensions have no root value. Keeping
  // the node lets an untouched save preserve the established v1 shape.
  return node;
}

function draftFromTemplateField(
  field: CategorySpecField,
  node: Record<string, unknown> | undefined,
): ProductSpecDraft {
  const unit = field.unit ?? cleanString(node?.unit);
  const normalizedValue =
    field.key === "dimensions" && node
      ? dimensionInputValue(node, unit)
      : normalizedValueForNode(node, field.value_type);
  const inputValue = formatSpecInputValue(normalizedValue);
  return {
    key: field.key,
    target: field.target,
    labelZh: field.label_zh,
    labelEn: field.label_en,
    valueType: field.key === "dimensions" ? "text" : field.value_type,
    unit,
    required: field.required,
    enumOptions: field.enum_options ?? [],
    hintZh: field.hint_zh ?? "",
    inputValue,
    normalizedValue,
    rawValue: cleanString(node?.raw_value),
    sourceLabel: cleanString(node?.source_label) || field.label_zh,
    origin: node ? "saved" : "empty",
    fromTemplate: true,
    dirty: false,
    preserveSourceEvidence: shouldPreserveSourceEvidence(node, inputValue),
    originalNode: node,
  };
}

function draftFromStoredStandard(
  key: string,
  node: Record<string, unknown>,
): ProductSpecDraft {
  const directValue = node.value_en ?? node.value;
  const normalizedValue =
    key === "dimensions"
      ? dimensionInputValue(node, cleanString(node.unit))
      : directValue === undefined || directValue === null
        ? node
        : directValue;
  const inputValue = formatSpecInputValue(normalizedValue);
  return {
    key,
    target: "standard",
    labelZh: cleanString(node.source_label) || key,
    labelEn: cleanString(node.label_en),
    valueType: inferValueType(directValue),
    unit: cleanString(node.unit),
    required: false,
    enumOptions: [],
    hintZh: "",
    inputValue,
    normalizedValue,
    rawValue: cleanString(node.raw_value),
    sourceLabel: cleanString(node.source_label) || key,
    origin: "saved",
    fromTemplate: false,
    dirty: false,
    preserveSourceEvidence: shouldPreserveSourceEvidence(node, inputValue),
    originalNode: node,
  };
}

function draftFromStoredAdditional(
  item: Record<string, unknown>,
  fallbackKey: string,
): ProductSpecDraft {
  const normalizedValue = item.value_en ?? item.value;
  const inputValue = formatSpecInputValue(normalizedValue);
  return {
    key: cleanString(item.key) || fallbackKey,
    target: "additional",
    labelZh: cleanString(item.label) || cleanString(item.source_label),
    labelEn: cleanString(item.label_en),
    valueType: inferValueType(normalizedValue),
    unit: cleanString(item.unit),
    required: false,
    enumOptions: [],
    hintZh: "",
    inputValue,
    normalizedValue,
    rawValue: cleanString(item.raw_value),
    sourceLabel:
      cleanString(item.source_label) || cleanString(item.label) || fallbackKey,
    origin: "saved",
    fromTemplate: false,
    dirty: false,
    preserveSourceEvidence: shouldPreserveSourceEvidence(item, inputValue),
    originalNode: item,
  };
}

export function productSpecDraftsFromStored(
  template: CategorySpecTemplate | null,
  structuredSpecs: Record<string, unknown> | null | undefined,
): ProductSpecDraft[] {
  const specs = isRecord(structuredSpecs) ? structuredSpecs : {};
  const additional = Array.isArray(specs.additional_specs)
    ? specs.additional_specs.filter(isRecord)
    : [];
  const additionalByKey = new Map(
    additional
      .map((item) => [cleanString(item.key), item] as const)
      .filter(([key]) => Boolean(key)),
  );
  const activeTemplate = template?.status === "approved" ? template : null;
  const templateKeys = new Set(activeTemplate?.fields.map((field) => field.key) ?? []);
  const drafts = (activeTemplate?.fields ?? []).map((field) => {
    const storedStandardNode = specs[field.key];
    const node =
      field.target === "standard"
        ? isRecord(storedStandardNode)
          ? storedStandardNode
          : undefined
        : additionalByKey.get(field.key);
    return draftFromTemplateField(field, node);
  });

  for (const key of STANDARD_SPEC_KEYS) {
    if (templateKeys.has(key) || ROOT_METADATA_KEYS.has(key)) {
      continue;
    }
    const node = specs[key];
    if (isRecord(node)) {
      drafts.push(draftFromStoredStandard(key, node));
    }
  }

  additional.forEach((item, index) => {
    const key = cleanString(item.key);
    if (key && templateKeys.has(key)) {
      return;
    }
    drafts.push(
      draftFromStoredAdditional(item, key || `operator_attribute_${index + 1}`),
    );
  });
  return drafts;
}

export function nextOperatorSpecKey(drafts: ProductSpecDraft[]) {
  const occupied = new Set(drafts.map((draft) => draft.key));
  let ordinal = 1;
  while (occupied.has(`operator_attribute_${ordinal}`)) {
    ordinal += 1;
  }
  return `operator_attribute_${ordinal}`;
}

export function newManualSpecDraft(drafts: ProductSpecDraft[]): ProductSpecDraft {
  const key = nextOperatorSpecKey(drafts);
  return {
    key,
    target: "additional",
    labelZh: "",
    labelEn: "",
    valueType: "text",
    unit: "",
    required: false,
    enumOptions: [],
    hintZh: "",
    inputValue: "",
    normalizedValue: undefined,
    rawValue: "",
    sourceLabel: "",
    origin: "empty",
    fromTemplate: false,
    dirty: false,
    preserveSourceEvidence: false,
  };
}

export function normalizedDraftInput(
  valueType: CategorySpecFieldValueType,
  inputValue: string,
): unknown {
  const value = inputValue.trim();
  if (!value) {
    return undefined;
  }
  if (valueType === "number") {
    const number = Number(value);
    return Number.isFinite(number) ? number : undefined;
  }
  if (valueType === "boolean") {
    if (value === "true") return true;
    if (value === "false") return false;
    return undefined;
  }
  return value;
}

export function updateProductSpecDraftValue(
  draft: ProductSpecDraft,
  inputValue: string,
): ProductSpecDraft {
  const retainParsedEvidence =
    draft.preserveSourceEvidence && Boolean(draft.rawValue);
  return {
    ...draft,
    inputValue,
    normalizedValue: normalizedDraftInput(draft.valueType, inputValue),
    rawValue: retainParsedEvidence ? draft.rawValue : inputValue,
    sourceLabel:
      retainParsedEvidence && draft.sourceLabel
        ? draft.sourceLabel
        : draft.labelZh || draft.key,
    origin: "manual",
    dirty: true,
    preserveSourceEvidence: retainParsedEvidence,
  };
}

export function applyPasteResultToDrafts(
  drafts: ProductSpecDraft[],
  result: SpecPasteParseResponse,
): ProductSpecDraft[] {
  return drafts.map((draft) => {
    if (!draft.fromTemplate) {
      return draft;
    }
    const match = result.matched[draft.key];
    if (!match) {
      return draft;
    }
    return {
      ...draft,
      inputValue: formatSpecInputValue(match.value),
      normalizedValue: match.value,
      rawValue: match.raw_value,
      sourceLabel: match.source_label,
      origin: "ai",
      dirty: true,
      preserveSourceEvidence: true,
    };
  });
}

export function hasProductSpecDraftValue(draft: ProductSpecDraft) {
  return draft.inputValue.trim().length > 0;
}

export function missingRequiredDraftKeys(drafts: ProductSpecDraft[]) {
  return drafts
    .filter(
      (draft) =>
        draft.fromTemplate && draft.required && !hasProductSpecDraftValue(draft),
    )
    .map((draft) => draft.key);
}

function buyerFacingValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value !== "string") {
    return undefined;
  }
  const cleaned = value.trim();
  return cleaned && !containsCjk(cleaned) ? cleaned : undefined;
}

function canonicalDraftValue(draft: ProductSpecDraft) {
  if (!draft.dirty && draft.normalizedValue !== undefined) {
    return draft.normalizedValue;
  }
  const normalized = normalizedDraftInput(draft.valueType, draft.inputValue);
  if (normalized === undefined) {
    throw new Error(
      draft.valueType === "number"
        ? `「${draft.labelZh || draft.key}」必须填写有效数字。`
        : `「${draft.labelZh || draft.key}」的值无效。`,
    );
  }
  return normalized;
}

export function buildOperatorStructuredSpecs(
  drafts: ProductSpecDraft[],
): Record<string, unknown> | null {
  const populated: ProductSpecDraft[] = [];
  const seenKeys = new Set<string>();

  for (const draft of drafts) {
    const touchedManualRow =
      !draft.fromTemplate &&
      Boolean(draft.labelZh.trim() || draft.inputValue.trim() || draft.unit.trim());
    if (touchedManualRow && (!draft.labelZh.trim() || !draft.inputValue.trim())) {
      throw new Error("每条额外规格必须同时填写规格名和真实值；未知项请留空。");
    }
    if (!hasProductSpecDraftValue(draft)) {
      continue;
    }
    if (seenKeys.has(draft.key)) {
      throw new Error(`规格 key 重复：${draft.key}`);
    }
    seenKeys.add(draft.key);
    populated.push(draft);
  }

  if (populated.length === 0) {
    return null;
  }

  const output: Record<string, unknown> = {
    schema_version: "1.0",
    source: { platform: "operator" },
  };
  const additional: Record<string, unknown>[] = [];

  for (const draft of populated) {
    const value = canonicalDraftValue(draft);
    const rawValue = draft.rawValue.trim() || draft.inputValue.trim();
    const sourceLabel =
      draft.sourceLabel.trim() || draft.labelZh.trim() || draft.key;
    const valueEn = buyerFacingValue(value);

    if (draft.target === "standard") {
      const node: Record<string, unknown> =
        !draft.dirty && draft.originalNode
          ? { ...draft.originalNode }
          : { value };
      if (draft.dirty || !draft.originalNode) {
        node.value = value;
      }
      if (rawValue) node.raw_value = rawValue;
      if (sourceLabel) node.source_label = sourceLabel;
      if (draft.labelEn.trim()) node.label_en = draft.labelEn.trim();
      if (draft.unit.trim()) node.unit = draft.unit.trim();
      if (valueEn) node.value_en = valueEn;
      output[draft.key] = node;
      continue;
    }

    const item: Record<string, unknown> = {
      key: draft.key,
      label: draft.labelZh.trim(),
      source_label: sourceLabel,
      value,
      raw_value: rawValue,
    };
    if (draft.labelEn.trim()) item.label_en = draft.labelEn.trim();
    if (draft.unit.trim()) item.unit = draft.unit.trim();
    if (valueEn) item.value_en = valueEn;
    additional.push(item);
  }

  if (additional.length > 0) {
    output.additional_specs = additional;
  }
  return output;
}

export function templateFieldValidationErrors(fields: CategorySpecField[]) {
  const errors: string[] = [];
  const keys = new Set<string>();
  if (fields.length === 0) {
    errors.push("模板至少需要一个字段。");
  }
  for (const field of fields) {
    const key = field.key.trim();
    if (!/^[a-z][a-z0-9_]{0,127}$/.test(key)) {
      errors.push(`key「${key || "（空）"}」必须是 snake_case 英文。`);
    } else if (keys.has(key)) {
      errors.push(`key「${key}」重复。`);
    }
    keys.add(key);
    if (!field.label_zh.trim()) {
      errors.push(`字段「${key || "（空）"}」缺少中文标签。`);
    }
    if (
      !field.label_en.trim() ||
      containsCjk(field.label_en) ||
      !/[A-Za-z]/.test(field.label_en)
    ) {
      errors.push(`字段「${key || "（空）"}」必须填写英文 label_en。`);
    }
    if (STANDARD_SPEC_KEYS.has(key) && field.target !== "standard") {
      errors.push(`标准键「${key}」必须使用 standard target。`);
    }
    if (key === "dimensions" && field.value_type !== "text") {
      errors.push("标准键「dimensions」必须使用 text 值类型（长 × 宽 × 高）。");
    }
    if (field.target === "standard" && !STANDARD_SPEC_KEYS.has(key)) {
      errors.push(`非标准键「${key}」不能使用 standard target。`);
    }
    if (field.value_type === "enum" && !(field.enum_options?.length)) {
      errors.push(`枚举字段「${key}」至少需要一个选项。`);
    }
  }
  return errors;
}

export function newCategorySpecField(fields: CategorySpecField[]): CategorySpecField {
  const occupied = new Set(fields.map((field) => field.key));
  let ordinal = 1;
  while (occupied.has(`custom_spec_${ordinal}`)) {
    ordinal += 1;
  }
  return {
    key: `custom_spec_${ordinal}`,
    target: "additional",
    label_zh: "",
    label_en: "",
    value_type: "text",
    unit: null,
    required: false,
    enum_options: null,
    hint_zh: null,
  };
}
