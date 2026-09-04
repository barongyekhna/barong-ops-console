// 「基础档案」面板（2026-09-04）：建好之后改类型/变体、尺寸重量、参考图链接。
//
// 三层守卫：
// (a) 代理白名单——新端点漏登记 = 前端红条（2026-08-04 事故的同款）；
// (b) form-helpers 的回填函数——读模型 JSON 变回表单输入，和建品表单的「表单 → JSON」互逆；
// (c) 源码不变量——面板真的挂在 ProductDetail 里，纯函数真的从 ProductForm 搬走了。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// form-helpers.ts 相对导入 `./display` 不带扩展名，node ESM 不会补，要挂上仓库的解析钩子；
// 静态 import 在钩子挂上之前就已解析，所以 form-helpers 必须动态 import。
register("./_alias-hooks.mjs", import.meta.url);

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";
const {
  buildVariantPayloads,
  dimensionsFormFromJson,
  PRODUCT_FORM_LABELS,
  TARGET_MARKETS,
  variantFormFromRead,
  weightFormFromJson,
} = await import("../../frontend/src/modules/k/product-knowledge/form-helpers.ts");

const here = path.dirname(fileURLToPath(import.meta.url));
const kDir = path.resolve(here, "../../frontend/src/modules/k/product-knowledge");
const uuid = "01234567-89ab-4def-8123-456789abcdef";

test("代理白名单放行 PUT variants / POST reference-images，拒绝邻近形状", () => {
  const allowed = [
    ["PUT", ["k", "products", uuid, "variants"]],
    ["POST", ["k", "products", uuid, "reference-images"]],
  ];
  const denied = [
    ["POST", ["k", "products", uuid, "variants"]],
    ["PATCH", ["k", "products", uuid, "variants"]],
    ["DELETE", ["k", "products", uuid, "variants"]],
    ["GET", ["k", "products", uuid, "reference-images"]],
    ["PUT", ["k", "products", uuid, "reference-images"]],
    ["PUT", ["k", "products", "not-a-uuid", "variants"]],
    ["PUT", ["k", "products", uuid, "variants", "extra"]],
  ];
  for (const [method, segments] of allowed) {
    assert.equal(isAllowedBackendProxyPath(method, segments), true, `${method} ${segments.join("/")}`);
    assert.equal(getBackendApiPath(method, segments), `/api/app/${segments.join("/")}`);
  }
  for (const [method, segments] of denied) {
    assert.equal(isAllowedBackendProxyPath(method, segments), false, `${method} ${segments.join("/")}`);
  }
});

test("dimensionsFormFromJson / weightFormFromJson 优先回填 source 原值", () => {
  const dims = dimensionsFormFromJson(
    {
      length: 3.937,
      width: 1.969,
      height: 0.787,
      unit: "inch",
      source: { length: 10, width: 5, height: 2, unit: "cm" },
    },
    "inch",
  );
  assert.deepEqual(dims, { height: "2", length: "10", unit: "cm", width: "5" });

  // 没有 source（别的路径写的 JSON）→ 用顶层值
  assert.deepEqual(dimensionsFormFromJson({ length: 12, width: 8, height: 6, unit: "inch" }, "cm"), {
    height: "6",
    length: "12",
    unit: "inch",
    width: "8",
  });
  // 空 / 非法 → 空输入 + 默认单位
  assert.deepEqual(dimensionsFormFromJson(null, "inch"), { height: "", length: "", unit: "inch", width: "" });
  assert.deepEqual(dimensionsFormFromJson({ unit: "furlong" }, "cm"), { height: "", length: "", unit: "cm", width: "" });

  assert.deepEqual(weightFormFromJson({ value: 1.2, unit: "lb", source: { value: 544, unit: "g" } }, "lb"), {
    unit: "g",
    value: "544",
  });
  assert.deepEqual(weightFormFromJson(undefined, "lb"), { unit: "lb", value: "" });
});

test("variantFormFromRead：建品表单写的属性、physical、参考图都回得来", () => {
  const row = variantFormFromRead(
    {
      id: "v1",
      product_id: "p1",
      parent_sku: "PSPE-003",
      variant_sku: "PSPE-003-5E9CCD48",
      variant_hash: "5E9CCD48",
      color: "Blue",
      size: null,
      function: null,
      quantity: 2,
      price_override: 19.99,
      attributes_json: {
        attribute_schema: "attribute_builder_v1",
        variant_attributes: [
          { type: "color", value: "Blue" },
          { type: "quantity", value: "2" },
        ],
        physical: {
          dimensions: { length: 4, width: 3, height: 2, unit: "inch", source: { length: 10, width: 8, height: 5, unit: "cm" } },
          weight: { value: 1.1, unit: "lb" },
        },
        reference_image_url: "https://cbu01.alicdn.com/img/blue.jpg",
      },
      image_folder: "images/x/PSPE-003-5E9CCD48",
      status: "active",
      created_at: "2026-09-04T00:00:00Z",
      updated_at: "2026-09-04T00:00:00Z",
    },
    { dimensions: "inch", weight: "lb" },
  );
  assert.equal(row.variant_id, "v1");
  assert.equal(row.variant_sku, "PSPE-003-5E9CCD48");
  assert.deepEqual(row.attributes, [
    { type: "color", value: "Blue" },
    { type: "quantity", value: "2" },
  ]);
  assert.equal(row.price_override, "19.99");
  assert.deepEqual(row.dimensions_input, { height: "5", length: "10", unit: "cm", width: "8" });
  assert.deepEqual(row.weight_input, { unit: "lb", value: "1.1" });
  assert.equal(row.reference_image_url, "https://cbu01.alicdn.com/img/blue.jpg");
});

test("variantFormFromRead：F 搬进来的 default 行没有 variant_attributes，按列拼属性", () => {
  const base = {
    id: "v1", product_id: "p1", parent_sku: "PSPE-003", variant_sku: "PSPE-003-AAAAAAAA", variant_hash: "AAAAAAAA",
    image_folder: "", status: "active", created_at: "", updated_at: "",
  };
  const fromDefault = variantFormFromRead(
    { ...base, color: null, size: null, function: null, quantity: null, price_override: null, attributes_json: { default_variant: true } },
    { dimensions: "inch", weight: "lb" },
  );
  assert.deepEqual(fromDefault.attributes, []);
  assert.equal(fromDefault.price_override, "");
  assert.deepEqual(fromDefault.dimensions_input, { height: "", length: "", unit: "inch", width: "" });

  const fromColumns = variantFormFromRead(
    { ...base, color: "Green", size: "L", function: null, quantity: null, price_override: 5, attributes_json: null },
    { dimensions: "inch", weight: "lb" },
  );
  assert.deepEqual(fromColumns.attributes, [
    { type: "color", value: "Green" },
    { type: "size", value: "L" },
  ]);
});

test("回填后再经 buildVariantPayloads 装配，得到与建品同形的 payload（互逆）", () => {
  const market = TARGET_MARKETS.find((item) => item.code === "US");
  const labels = PRODUCT_FORM_LABELS.zh;
  const row = variantFormFromRead(
    {
      id: "v1", product_id: "p1", parent_sku: "X", variant_sku: "X-1", variant_hash: "1",
      color: "Blue", size: null, function: null, quantity: null, price_override: 19.99,
      attributes_json: {
        variant_attributes: [{ type: "color", value: "Blue" }],
        physical: { weight: { value: 1.2, unit: "lb", source: { value: 1.2, unit: "lb" } } },
      },
      image_folder: "", status: "active", created_at: "", updated_at: "",
    },
    { dimensions: "inch", weight: "lb" },
  );
  const built = buildVariantPayloads([row], market, labels);
  assert.equal(built.ok, true);
  const [payload] = built.value;
  assert.equal(payload.color, "Blue");
  assert.equal(payload.price_override, 19.99);
  assert.equal(payload.dimensions_json, null);
  assert.equal(payload.weight_json.value, 1.2);
  assert.equal(payload.weight_json.unit, "lb");
  assert.deepEqual(payload.attributes.variant_attributes, [{ type: "color", value: "Blue" }]);
});

test("源码不变量：面板挂在 ProductDetail，纯函数已从 ProductForm 搬走", () => {
  const detail = readFileSync(path.join(kDir, "ProductDetail.tsx"), "utf8");
  assert.match(detail, /<BasicDossierPanel/);
  assert.match(detail, /key=\{`dossier-\$\{currentShippingProduct\.id\}`\}/);
  const form = readFileSync(path.join(kDir, "ProductForm.tsx"), "utf8");
  assert.doesNotMatch(form, /^function buildVariantPayloads/m);
  assert.doesNotMatch(form, /^function normalizeDimensionsInput/m);
  assert.match(form, /from "\.\/form-helpers"/);
  const helpers = readFileSync(path.join(kDir, "form-helpers.ts"), "utf8");
  assert.match(helpers, /^export function buildVariantPayloads/m);
});
