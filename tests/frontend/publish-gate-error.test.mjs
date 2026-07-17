import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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

test("K dispatch error path preserves and renders P blockers", () => {
  const apiSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/api.ts",
    "utf8",
  );
  const productListSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductList.tsx",
    "utf8",
  );

  assert.match(apiSource, /parsePublishGateConflictDetail\(payload\.detail\)/);
  assert.match(
    productListSource,
    /publishGateConflictMessage\(label, error\.detail\)/,
  );
});
