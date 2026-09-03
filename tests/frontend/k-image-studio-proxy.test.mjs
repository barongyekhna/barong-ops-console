import assert from "node:assert/strict";
import test from "node:test";

import {
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

/**
 * 前端代理有显式白名单：K 的每个端点都要在 route.ts 里登记，漏登记的端点
 * 前端一调就被代理挡下，页面上表现为一条红色报错条 —— 后端明明是好的。
 *
 * 2026-08-04 实际踩到：作图工作台的 image-plates 和 operating-model 两个端点
 * 都没登记，浮窗打开即报错，而 backend 日志里连请求都看不到（根本没转发过去）。
 * 同类坑另见侧边栏的模块前缀白名单。
 */

const PRODUCT = "3f1d5b4a-7c62-4a1e-9b83-2f5c6d7e8a90";
const ASSET = "8a7b6c5d-4e3f-4a2b-9c1d-0e9f8a7b6c5d";

test("作图工作台的三个端点都在代理白名单里", () => {
  // 底板清单
  assert.equal(
    isAllowedBackendProxyPath("GET", ["k", "products", PRODUCT, "image-plates"]),
    true,
  );
  // 保存产品保护蒙版
  assert.equal(
    isAllowedBackendProxyPath("PUT", [
      "k", "products", PRODUCT, "image-plates", ASSET, "mask",
    ]),
    true,
  );
  // 人工修正「产品怎么工作」
  assert.equal(
    isAllowedBackendProxyPath("PUT", ["k", "products", PRODUCT, "operating-model"]),
    true,
  );
});

test("人工放行端点在白名单里", () => {
  // 2026-08-11：人的命令高于程序，但请求得先过得了代理这道门
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "k", "products", PRODUCT, "brand-audit", "override",
    ]),
    true,
  );
  // 原有的逐条忽略不能被带坏
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "k", "products", PRODUCT, "brand-audit", "ignore",
    ]),
    true,
  );
  // 别的动作名不放行
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "k", "products", PRODUCT, "brand-audit", "delete-all",
    ]),
    false,
  );
});

test("方法与形状不对的一律不放行", () => {
  // 只读端点不许写
  assert.equal(
    isAllowedBackendProxyPath("POST", ["k", "products", PRODUCT, "image-plates"]),
    false,
  );
  // 产品段必须是 uuid，挡住路径穿越/枚举
  assert.equal(
    isAllowedBackendProxyPath("GET", ["k", "products", "..", "image-plates"]),
    false,
  );
  // 资产段同样必须是 uuid
  assert.equal(
    isAllowedBackendProxyPath("PUT", [
      "k", "products", PRODUCT, "image-plates", "not-a-uuid", "mask",
    ]),
    false,
  );
  // 少一段/多一段都不放行
  assert.equal(
    isAllowedBackendProxyPath("PUT", ["k", "products", PRODUCT, "image-plates", ASSET]),
    false,
  );
});
