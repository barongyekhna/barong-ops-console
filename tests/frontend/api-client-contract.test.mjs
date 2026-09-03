// `lib/api.ts` 的**行为**契约测试。
//
// 为什么值得单开一份：B1 收口要把 17 个模块、197 处裸 fetch 迁到这一个函数上。
// 在那之前,关于 apiRequest 的全部断言都是「读源码匹配正则」—— 因为它 import
// 了 `@/lib/...` 别名、而且用了 TS 参数属性,node 根本 import 不进来。
// 源码断言证明不了「它在 204 上会不会抛」,而那恰恰是收口第一步就会撞上的东西。
//
// 现在两个障碍都拆了(`_alias-hooks.mjs` 解析别名;三个错误类改成显式字段),
// 所以这里是**真调用**:塞一个假 fetch,看它到底返回/抛出什么。

import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./_alias-hooks.mjs", import.meta.url);

const { ApiError, apiRequest } = await import("../../frontend/src/lib/api.ts");
const { clearFrontendRequestCache } = await import(
  "../../frontend/src/lib/request-cache.ts"
);

/** 记录每次 fetch 收到的参数，并按脚本返回响应。 */
function stubFetch(responder) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ init, url });
    return responder(calls.length - 1, init);
  };
  return calls;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

test.beforeEach(() => {
  clearFrontendRequestCache();
});

test("204 不带响应体时返回 undefined，而不是抛 SyntaxError", async () => {
  stubFetch(() => new Response(null, { status: 204 }));

  // 改之前这里会抛 SyntaxError（对空字符串调 response.json()）。
  // DELETE 类接口大量返回 204，所以这条是收口第一步的硬门槛。
  const result = await apiRequest("/w/sources/1", { method: "DELETE" });
  assert.equal(result, undefined);
});

test("205 同样按无响应体处理", async () => {
  stubFetch(() => new Response(null, { status: 205 }));
  assert.equal(await apiRequest("/w/sources/1", { method: "DELETE" }), undefined);
});

test("200 带响应体照常解析（正对照：上面两条不是把所有响应都吞成 undefined）", async () => {
  stubFetch(() => jsonResponse({ id: 7, name: "ok" }));
  assert.deepEqual(await apiRequest("/w/sources"), { id: 7, name: "ok" });
});

test("FormData 原样传给 fetch，且不扣上 application/json", async () => {
  const calls = stubFetch(() => jsonResponse({ ok: true }));

  const form = new FormData();
  form.append("file", new Blob(["hello"]), "a.txt");
  await apiRequest("/k/images/upload", { body: form, method: "POST" });

  const sent = calls[0].init;
  // multipart 的 boundary 是 fetch 按 FormData 自己生成写进 Content-Type 的。
  // 手动设成 application/json，boundary 就没了，后端解析必然失败。
  assert.ok(sent.body instanceof FormData, "FormData 被 JSON.stringify 破坏了");
  assert.equal(
    sent.headers.get("Content-Type"),
    null,
    "不该手动设 Content-Type，否则 multipart boundary 丢失",
  );
  assert.equal(sent.body.get("file").name, "a.txt");
});

test("普通对象 body 仍然序列化成 JSON（正对照）", async () => {
  const calls = stubFetch(() => jsonResponse({ ok: true }));
  await apiRequest("/w/sources", { body: { name: "x" }, method: "POST" });

  assert.equal(calls[0].init.headers.get("Content-Type"), "application/json");
  assert.equal(calls[0].init.body, JSON.stringify({ name: "x" }));
});

test("两个并发 FormData 上传不会被合并成一个", async () => {
  // 缓存 key 由 body 稳定序列化而来，而 FormData 走 Object.keys() 是空的 ——
  // 修之前两个内容完全不同的上传都算出 `body:{}`，撞进对所有方法都生效的
  // in-flight 去重，**第二个上传直接拿到第一个的结果**。那不是缓存失效，是数据错乱。
  const calls = stubFetch((index) => jsonResponse({ index }));

  const formA = new FormData();
  formA.append("file", new Blob(["A"]), "a.txt");
  const formB = new FormData();
  formB.append("file", new Blob(["B"]), "b.txt");

  const [a, b] = await Promise.all([
    apiRequest("/k/images/upload", { body: formA, method: "POST" }),
    apiRequest("/k/images/upload", { body: formB, method: "POST" }),
  ]);

  assert.equal(calls.length, 2, "两个上传被合并成了一次请求");
  assert.notDeepEqual(a, b, "第二个上传拿到了第一个的响应");
  assert.deepEqual(calls[0].init.body.get("file").name, "a.txt");
  assert.deepEqual(calls[1].init.body.get("file").name, "b.txt");
});

test("ApiError 带出后端的结构化 detail", async () => {
  stubFetch(() =>
    jsonResponse(
      { detail: { blockers: ["缺少主图", "缺少卖点"], message: "发布被拦下" } },
      400,
    ),
  );

  const error = await apiRequest("/k/products/1/publish", { method: "POST" })
    .then(() => null)
    .catch((caught) => caught);

  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 400);
  assert.equal(error.message, "发布被拦下");
  // message 是给人看的一句话，会被翻译器改写、被中文兜底整句换掉；
  // 结构化清单只能从 detail 读。以前它在 apiRequest 内部解析出来后就被丢了，
  // K 的发布门禁 blockers 和 M 的缺料清单于是静默消失。
  assert.deepEqual(error.detail.blockers, ["缺少主图", "缺少卖点"]);
});

test("detail 是纯字符串时也带出来，不是只有对象才给", async () => {
  stubFetch(() => jsonResponse({ detail: "库存不足" }, 409));
  const error = await apiRequest("/m/inventory/ship", { method: "POST" })
    .then(() => null)
    .catch((caught) => caught);

  assert.equal(error.message, "库存不足");
  assert.equal(error.detail, "库存不足");
});

test("后端没返回 JSON 时 detail 是 null，不是崩掉", async () => {
  stubFetch(() => new Response("<html>502</html>", { status: 502 }));
  const error = await apiRequest("/w/sources").then(() => null).catch((c) => c);

  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 502);
  assert.equal(error.detail, null);
});
