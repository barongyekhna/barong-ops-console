import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyPasteResultToDrafts,
  buildOperatorStructuredSpecs,
  missingRequiredDraftKeys,
  productSpecDraftsFromStored,
  templateFieldValidationErrors,
  updateProductSpecDraftValue,
} from "../../frontend/src/modules/k/product-knowledge/spec-template.ts";

const approvedTemplate = {
  category_id: "123",
  category_tree: "google",
  status: "approved",
  fields: [
    {
      key: "battery_capacity_mah",
      target: "standard",
      label_zh: "电池容量",
      label_en: "Battery capacity",
      value_type: "number",
      unit: "mAh",
      required: true,
      enum_options: null,
      hint_zh: "额定容量",
    },
    {
      key: "main_pot_capacity",
      target: "additional",
      label_zh: "主锅容量",
      label_en: "Main pot capacity",
      value_type: "text",
      unit: "L",
      required: true,
      enum_options: null,
      hint_zh: null,
    },
  ],
};

test("Round 9 paste fills only matched template fields and preserves evidence layers", () => {
  const initial = productSpecDraftsFromStored(approvedTemplate, {
    schema_version: "1.0",
    source: { platform: "operator" },
    material: {
      value: "Aluminum",
      raw_value: "Aluminum",
      source_label: "Material",
    },
  });

  const parsed = applyPasteResultToDrafts(initial, {
    matched: {
      battery_capacity_mah: {
        value: 2200,
        raw_value: "2200mAh",
        source_label: "电池容量",
      },
      main_pot_capacity: {
        value: "1.5 L",
        raw_value: "1.5升",
        source_label: "主锅容积",
      },
    },
    missing_required: [],
    unmatched_lines: ["颜色 红色"],
  });

  assert.equal(parsed.find((row) => row.key === "battery_capacity_mah").origin, "ai");
  assert.equal(parsed.find((row) => row.key === "material").origin, "saved");
  assert.deepEqual(missingRequiredDraftKeys(parsed), []);

  const payload = buildOperatorStructuredSpecs(parsed);
  assert.equal(payload.battery_capacity_mah.value, 2200);
  assert.equal(payload.battery_capacity_mah.raw_value, "2200mAh");
  assert.equal(payload.battery_capacity_mah.source_label, "电池容量");
  assert.equal(payload.material.value, "Aluminum");
  assert.equal(
    payload.additional_specs.find((row) => row.key === "main_pot_capacity").label_en,
    "Main pot capacity",
  );
  assert.equal(
    payload.additional_specs.find((row) => row.key === "main_pot_capacity").value_en,
    "1.5 L",
  );
  assert.equal(
    payload.additional_specs.find((row) => row.key === "main_pot_capacity").raw_value,
    "1.5升",
  );
  assert.equal(
    payload.additional_specs.find((row) => row.key === "main_pot_capacity").source_label,
    "主锅容积",
  );
});

test("Round 9 parser never fills unmatched fields", () => {
  const initial = productSpecDraftsFromStored(approvedTemplate, null);
  const parsed = applyPasteResultToDrafts(initial, {
    matched: {
      battery_capacity_mah: {
        value: 1800,
        raw_value: "1800mAh",
        source_label: "容量",
      },
    },
    missing_required: ["main_pot_capacity"],
    unmatched_lines: [],
  });

  assert.equal(
    parsed.find((row) => row.key === "main_pot_capacity").inputValue,
    "",
  );
  assert.deepEqual(missingRequiredDraftKeys(parsed), ["main_pot_capacity"]);
});

test("AI evidence survives repeated operator edits", () => {
  const initial = productSpecDraftsFromStored(approvedTemplate, null);
  let parsed = applyPasteResultToDrafts(initial, {
    matched: {
      main_pot_capacity: {
        value: "1.5 L",
        raw_value: "1.5升",
        source_label: "主锅容积",
      },
    },
    missing_required: ["battery_capacity_mah"],
    unmatched_lines: [],
  });
  parsed = parsed.map((draft) =>
    draft.key === "main_pot_capacity"
      ? updateProductSpecDraftValue(draft, "1.6 L")
      : draft,
  );
  parsed = parsed.map((draft) =>
    draft.key === "main_pot_capacity"
      ? updateProductSpecDraftValue(draft, "1.7 L")
      : draft,
  );

  const item = buildOperatorStructuredSpecs(parsed).additional_specs[0];
  assert.equal(item.value, "1.7 L");
  assert.equal(item.raw_value, "1.5升");
  assert.equal(item.source_label, "主锅容积");
});

test("standard dimensions render as editable L x W x H and retain template units", () => {
  const template = {
    ...approvedTemplate,
    fields: [
      {
        key: "dimensions",
        target: "standard",
        label_zh: "产品尺寸",
        label_en: "Product dimensions",
        value_type: "number",
        unit: "mm",
        required: true,
        enum_options: null,
        hint_zh: "长 × 宽 × 高",
      },
    ],
  };
  const drafts = productSpecDraftsFromStored(template, {
    schema_version: "1.0",
    source: { platform: "operator" },
    dimensions: {
      unit: "cm",
      length: { value: 12 },
      width: { value: 8 },
      height: { value: 4 },
    },
  });

  assert.equal(drafts[0].inputValue, "120 × 80 × 40");
  assert.equal(drafts[0].unit, "mm");
  assert.equal(drafts[0].valueType, "text");
  const edited = updateProductSpecDraftValue(drafts[0], "125 × 85 × 45");
  const payload = buildOperatorStructuredSpecs([edited]);
  assert.equal(payload.dimensions.value, "125 × 85 × 45");
  assert.equal(payload.dimensions.raw_value, "125 × 85 × 45");
  assert.equal(payload.dimensions.unit, "mm");
});

test("additional numeric matches retain a buyer-facing normalized value", () => {
  const template = {
    ...approvedTemplate,
    fields: [
      {
        ...approvedTemplate.fields[1],
        value_type: "number",
      },
    ],
  };
  const parsed = applyPasteResultToDrafts(
    productSpecDraftsFromStored(template, null),
    {
      matched: {
        main_pot_capacity: {
          value: 1.5,
          raw_value: "1.5升",
          source_label: "主锅容积",
        },
      },
      missing_required: [],
      unmatched_lines: [],
    },
  );

  const item = buildOperatorStructuredSpecs(parsed).additional_specs[0];
  assert.equal(item.value, 1.5);
  assert.equal(item.value_en, "1.5");
  assert.equal(item.unit, "L");
});

test("additional boolean matches keep false distinct from missing", () => {
  const template = {
    ...approvedTemplate,
    fields: [
      {
        key: "has_lid",
        target: "additional",
        label_zh: "是否带盖",
        label_en: "Lid included",
        value_type: "boolean",
        unit: null,
        required: true,
        enum_options: null,
        hint_zh: null,
      },
    ],
  };
  const parsed = applyPasteResultToDrafts(
    productSpecDraftsFromStored(template, null),
    {
      matched: {
        has_lid: {
          value: false,
          raw_value: "否",
          source_label: "是否带盖",
        },
      },
      missing_required: [],
      unmatched_lines: [],
    },
  );

  assert.deepEqual(missingRequiredDraftKeys(parsed), []);
  const item = buildOperatorStructuredSpecs(parsed).additional_specs[0];
  assert.equal(item.value, false);
  assert.equal(item.raw_value, "否");
  assert.equal(item.value_en, "No");
});

test("typed additional values survive a save and reload round trip", () => {
  const template = {
    ...approvedTemplate,
    fields: [
      {
        ...approvedTemplate.fields[1],
        value_type: "number",
      },
      {
        key: "has_lid",
        target: "additional",
        label_zh: "是否带盖",
        label_en: "Lid included",
        value_type: "boolean",
        unit: null,
        required: true,
        enum_options: null,
        hint_zh: null,
      },
    ],
  };
  const parsed = applyPasteResultToDrafts(
    productSpecDraftsFromStored(template, null),
    {
      matched: {
        main_pot_capacity: {
          value: 1.5,
          raw_value: "1.5升",
          source_label: "主锅容积",
        },
        has_lid: {
          value: false,
          raw_value: "否",
          source_label: "是否带盖",
        },
      },
      missing_required: [],
      unmatched_lines: [],
    },
  );
  const saved = buildOperatorStructuredSpecs(parsed);
  const reloaded = productSpecDraftsFromStored(template, saved);

  assert.equal(
    reloaded.find((draft) => draft.key === "main_pot_capacity").inputValue,
    "1.5",
  );
  assert.equal(
    reloaded.find((draft) => draft.key === "has_lid").inputValue,
    "false",
  );
  assert.deepEqual(missingRequiredDraftKeys(reloaded), []);
});

test("required number zero and boolean false are retained as real values", () => {
  const template = {
    ...approvedTemplate,
    fields: [
      { ...approvedTemplate.fields[0], key: "runtime_h", unit: "h" },
      {
        key: "has_lid",
        target: "additional",
        label_zh: "是否带盖",
        label_en: "Lid included",
        value_type: "boolean",
        unit: null,
        required: true,
        enum_options: null,
        hint_zh: null,
      },
    ],
  };
  let drafts = productSpecDraftsFromStored(template, null);
  drafts = drafts.map((draft) =>
    draft.key === "runtime_h"
      ? updateProductSpecDraftValue(draft, "0")
      : updateProductSpecDraftValue(draft, "false"),
  );

  assert.deepEqual(missingRequiredDraftKeys(drafts), []);
  const payload = buildOperatorStructuredSpecs(drafts);
  assert.equal(payload.runtime_h.value, 0);
  assert.equal(payload.additional_specs[0].value, false);
});

test("draft templates remain inert until approved", () => {
  const drafts = productSpecDraftsFromStored(
    { ...approvedTemplate, status: "draft" },
    null,
  );
  assert.deepEqual(drafts, []);
  assert.deepEqual(missingRequiredDraftKeys(drafts), []);
});

test("template validation enforces snake_case, English labels and standard targets", () => {
  assert.deepEqual(templateFieldValidationErrors(approvedTemplate.fields), []);
  const errors = templateFieldValidationErrors([
    {
      ...approvedTemplate.fields[0],
      key: "Battery Capacity",
      label_en: "电池容量",
      target: "additional",
    },
  ]);
  assert.ok(errors.some((error) => error.includes("snake_case")));
  assert.ok(errors.some((error) => error.includes("label_en")));
});

test("ProductDetail delegates the whole specification workflow to ProductSpecsPanel", () => {
  const detailSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductDetail.tsx",
    "utf8",
  );
  const panelSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductSpecsPanel.tsx",
    "utf8",
  );

  assert.match(detailSource, /<ProductSpecsPanel/);
  assert.doesNotMatch(detailSource, /additional_specs:\s*populated\.map/);
  assert.match(panelSource, /parseProductSpecsPaste/);
  assert.match(panelSource, /parseRequestRef/);
  assert.match(panelSource, /structuredSpecsFingerprint/);
  assert.match(panelSource, /activeProductIdRef\.current !== productId/);
  assert.match(panelSource, /AI 起草模板|CategorySpecTemplateEditor/);
  assert.match(panelSource, /允许保存，但会阻断 K→P 上架/);
});

test("category management exposes a leaf-only template editor entry", () => {
  const listSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductList.tsx",
    "utf8",
  );
  const managerSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/CategoryTemplateManager.tsx",
    "utf8",
  );
  const pageSource = readFileSync(
    "frontend/src/app/(console)/products/categories/page.tsx",
    "utf8",
  );

  assert.match(listSource, /href="\/products\/categories"/);
  assert.match(pageSource, /<CategoryTemplateManager/);
  assert.match(managerSource, /searchCategories\(tree, term, 50\)/);
  assert.match(managerSource, /disabled=\{!item\.is_leaf\}/);
  assert.match(managerSource, /templateRequestRef/);
  assert.match(managerSource, /<CategorySpecTemplateEditor/);
});
