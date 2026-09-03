import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import test from "node:test";

// 被测模块 2026-09-02 收口到 `lib/api.ts` 之后带上了 `@/lib/...` 路径别名，
// 而 `node --test` 没有 Next 那套解析器 —— 静态 import 会直接 ERR_MODULE_NOT_FOUND。
// 先注册别名钩子，再动态 import（静态 import 会在 register 之前求值）。
register("./_alias-hooks.mjs", import.meta.url);

const {
  deleteProductSource,
  getProductSources,
  isHttpProductSourceUrl,
  normalizeProductSourceSku,
  upsertProductSource,
} = await import("../../frontend/src/modules/w/siteops/api.ts");

test("W-S 货源客户端使用规范化 SKU 与精确 CRUD 契约", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const source = {
    id: "01234567-89ab-4def-8123-456789abcdef",
    sku: "IGL-001",
    source_url: "https://detail.1688.com/offer/123.html",
    supplier_name: "示例供应商",
    unit_cost: "12.50",
    currency: "CNY",
    moq: 2,
    notes: null,
    created_at: null,
    updated_at: null,
  };

  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (init.method === "GET") {
      return Response.json({
        items: [source],
        page: 2,
        page_size: 50,
        total: 51,
        pages: 2,
      });
    }
    if (init.method === "PUT") return Response.json(source);
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    throw new Error(`unexpected method ${init.method}`);
  };

  try {
    const listed = await getProductSources(" igl ", 2);
    const saved = await upsertProductSource(" igl-001 ", {
      source_url: source.source_url,
      supplier_name: source.supplier_name,
      unit_cost: 12.5,
      currency: "CNY",
      moq: 2,
      notes: null,
    });
    await deleteProductSource(" igl-001 ");

    assert.equal(listed.total, 51);
    assert.equal(saved.sku, "IGL-001");
    assert.equal(
      calls[0].url,
      "/api/backend/w/sources?query=igl&page=2",
    );
    assert.equal(calls[1].url, "/api/backend/w/sources/IGL-001");
    assert.equal(calls[1].init.method, "PUT");
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      source_url: source.source_url,
      supplier_name: source.supplier_name,
      unit_cost: 12.5,
      currency: "CNY",
      moq: 2,
      notes: null,
    });
    assert.equal(calls[2].url, "/api/backend/w/sources/IGL-001");
    assert.equal(calls[2].init.method, "DELETE");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("W-S 货源输入只接受 http/https 并统一 SKU", () => {
  assert.equal(normalizeProductSourceSku(" igl-001 "), "IGL-001");
  assert.equal(
    isHttpProductSourceUrl("https://detail.1688.com/offer/123.html"),
    true,
  );
  assert.equal(isHttpProductSourceUrl("http://example.test/source"), true);
  assert.equal(isHttpProductSourceUrl("javascript:alert(1)"), false);
  assert.equal(isHttpProductSourceUrl("not-a-url"), false);
});

test("W-S 页面覆盖货源直达、缺失补录与同页货源库", () => {
  const deck = readFileSync(
    "frontend/src/modules/w/siteops/ShippingDeck.tsx",
    "utf8",
  );
  const panel = readFileSync(
    "frontend/src/modules/w/siteops/ProductSourcesPanel.tsx",
    "utf8",
  );

  assert.match(deck, /item\.source_state === "linked"/);
  assert.match(deck, /target="_blank"/);
  assert.match(deck, /rel="noopener noreferrer"/);
  assert.match(deck, /1688 下单 ↗/);
  assert.match(deck, /补货源/);
  assert.match(deck, /handleInlineSourceSaved/);
  assert.match(deck, /activeTab === "sources"/);
  assert.match(panel, /搜索 SKU 或供应商/);
  assert.match(panel, /新增货源/);
  assert.match(panel, /"编辑"/);
  assert.match(panel, /"删除"/);
});
