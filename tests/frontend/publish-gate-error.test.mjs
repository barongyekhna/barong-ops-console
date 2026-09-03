import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import test from "node:test";

// K 的 api.ts 收口后带上了 `@/lib/...` 别名，`node --test` 没有 Next 的解析器。
register("./_alias-hooks.mjs", import.meta.url);

import {
  parsePublishGateConflictDetail,
  publishGateConflictMessage,
} from "../../frontend/src/modules/k/product-knowledge/publish-gate-error.ts";

test("K frontend accepts only the exact safe P publish-gate conflict shape", () => {
  const detail = {
    ready: false,
    blockers: ["价格缺失", "未绑定类目"],
  };

  assert.deepEqual(parsePublishGateConflictDetail(detail), detail);
  assert.equal(
    publishGateConflictMessage("Trail Stove", detail),
    "「Trail Stove」未过上架门禁：价格缺失；未绑定类目",
  );
  assert.equal(
    parsePublishGateConflictDetail({ ...detail, debug: "hidden" }),
    null,
  );
  assert.equal(
    parsePublishGateConflictDetail({ ready: false, blockers: [42] }),
    null,
  );
});

// 2026-09-02：K 收口到 `lib/api.ts` 之后，这条从「读源码匹配正则」升级成
// **真调用**。源码断言证明不了「门禁 detail 到底有没有被白名单挡住」——
// 它只证明某个字符串出现在文件里，而那个字符串刚好在收口时换了写法。
test("上架门禁 409 的 blockers 会原样带到 UI，且只放行安全形状", async () => {
  const { ProductKnowledgeApiError, dispatchUpload } = await import(
    "../../frontend/src/modules/k/product-knowledge/api.ts"
  );

  const originalFetch = globalThis.fetch;
  const respondWith = (detail) => {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail }), {
        headers: { "Content-Type": "application/json" },
        status: 409,
      });
  };

  try {
    // 合法形状：detail 原样带到调用方，消息是门禁专用的那句。
    respondWith({ ready: false, blockers: ["价格缺失", "未绑定类目"] });
    const passed = await dispatchUpload("p-1").then(
      () => null,
      (error) => error,
    );
    assert.ok(passed instanceof ProductKnowledgeApiError);
    assert.equal(passed.status, 409);
    assert.equal(passed.message, "产品未通过上架门禁。");
    assert.deepEqual(passed.detail.blockers, ["价格缺失", "未绑定类目"]);
    assert.equal(
      publishGateConflictMessage("Trail Stove", passed.detail),
      "「Trail Stove」未过上架门禁：价格缺失；未绑定类目",
    );

    // 形状不吻合（多一个字段）：**不当成门禁结果**，走普通错误路径。
    respondWith({ ready: false, blockers: ["价格缺失"], debug: "hidden" });
    const tampered = await dispatchUpload("p-2").then(
      () => null,
      (error) => error,
    );
    assert.ok(tampered instanceof ProductKnowledgeApiError);
    assert.notEqual(tampered.message, "产品未通过上架门禁。");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ProductList 用 error.detail 渲染 blockers", () => {
  const productListSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductList.tsx",
    "utf8",
  );
  assert.match(
    productListSource,
    /publishGateConflictMessage\(label, error\.detail\)/,
  );
});
