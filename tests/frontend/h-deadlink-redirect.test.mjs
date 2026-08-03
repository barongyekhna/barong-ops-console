import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  isInternalUrl,
  suggestRedirectTarget,
  toRedirectPath,
} from "../../frontend/src/modules/h/sitehealth/redirect-hint.ts";

const read = (p) => readFileSync(`frontend/src/modules/h/sitehealth/${p}`, "utf8");

// ---------------------------------------------------------------- 纯函数

test("路径归一必须和插件的 by_rd_normalize 对齐（小写、去尾斜杠）", () => {
  // 对不齐的话跳转表里写了也匹配不上，页面照样 404 —— 而且**静默不生效**，不报错
  assert.equal(toRedirectPath("https://barongyekhna.com/product/x/"), "/product/x");
  assert.equal(toRedirectPath("https://barongyekhna.com/Product/X/"), "/product/x");
  assert.equal(toRedirectPath("https://barongyekhna.com/product/x"), "/product/x");
  assert.equal(toRedirectPath("https://barongyekhna.com/"), "/");
  assert.equal(toRedirectPath("https://barongyekhna.com"), "/");
  // fragment 不属于服务端能看到的东西，必须剥掉
  assert.equal(toRedirectPath("https://barongyekhna.com/a/#top"), "/a");
  // 查询串要留着：跳转表里已有 /?page_id=1759 这种键
  assert.equal(toRedirectPath("https://barongyekhna.com/?page_id=1759"), "/?page_id=1759");
  // 表里存的本来就是路径形式，要能原样吃进去
  assert.equal(toRedirectPath("/product/y/"), "/product/y");
  assert.equal(toRedirectPath(""), null);
});

test("只有本站地址才谈得上设跳转", () => {
  assert.equal(isInternalUrl("https://barongyekhna.com/x"), true);
  assert.equal(isInternalUrl("http://barongyekhna.com/x"), true);
  assert.equal(isInternalUrl("https://www.barongyekhna.com/x"), true);
  // 跳转插件只在**本站** 404 时生效，站外死链它管不着
  assert.equal(isInternalUrl("https://telegram.me/share"), false);
  assert.equal(isInternalUrl("https://barongsupply.com/x"), false);
  // 差点被当成自己人的：域名只是以本站结尾
  assert.equal(isInternalUrl("https://evilbarongyekhna.com/x"), false);
  assert.equal(isInternalUrl("http://url"), false);
  assert.equal(isInternalUrl("not-a-url"), false);
});

test("推荐目标按已有跳转的模式来，其余保守回首页", () => {
  assert.equal(suggestRedirectTarget("/product/gone"), "/shop-2/");
  assert.equal(suggestRedirectTarget("/product-category/gone"), "/shop-2/");
  assert.equal(suggestRedirectTarget("/some-page"), "/");
  // 传完整 URL 也要能用（调用方拿到的就是 finding.url）
  assert.equal(suggestRedirectTarget("https://barongyekhna.com/product/gone/"), "/shop-2/");
});

// ---------------------------------------------------------------- 接线

test("死链清单上有「设跳转」，且只给本站死链显示", () => {
  const deck = read("HealthDeck.tsx");
  assert.match(deck, /设跳转/);
  // 三个条件缺一不可：是死链、是本站、路径能归一
  assert.match(deck, /finding\.finding_type === "broken_link"/);
  assert.match(deck, /isInternalUrl\(finding\.url\)/);
  assert.match(deck, /canRedirect\(finding\)/);
});

test("「设跳转」把死链交给跳转管理面板，并切过去", () => {
  const workspace = read("SiteHealthWorkspace.tsx");
  assert.match(workspace, /onCreateRedirect/);
  assert.match(workspace, /setActiveTab\("redirects"\)/);
  assert.match(workspace, /handoff=\{handoff\}/);
});

test("跳转管理接住交接：预填路径 + 推荐目标 + 高亮那一行", () => {
  const panels = read("WpBridgePanels.tsx");
  assert.match(panels, /handoff/);
  assert.match(panels, /suggestRedirectTarget\(handoff\.path\)/);
  assert.match(panels, /focusRuleId/);
  // 同路径已有规则时不重复添加
  assert.match(panels, /toRedirectPath\(rule\.from\) === handoff\.path/);
});

test("必须实测跳转真生效，才敢把死链标成已解决", () => {
  const panels = read("WpBridgePanels.tsx");
  const save = panels.slice(panels.indexOf("const handleSave"));
  const verifyAt = save.indexOf("verifyWpRedirect(pendingFinding.path)");
  const resolveAt = save.indexOf('updateHealthFinding(pendingFinding.findingId, "resolve")');
  assert.ok(verifyAt > 0, "保存后要实测一次");
  assert.ok(resolveAt > 0, "验证通过要标记已解决");
  // 顺序不能反：先验证，通过了才标记
  assert.ok(verifyAt < resolveAt, "必须先验证再标记，不能报告成功而什么都没发生");
  // 验证不通过要显式说明没标记，而不是静默
  assert.match(panels, /没有\*\*标记为已解决|没有.{0,6}标记为已解决/);
});


test("死链清单只留「设跳转」和「忽略」——不给手动「已解决」", () => {
  const deck = read("HealthDeck.tsx");
  assert.match(deck, /设跳转/);
  assert.match(deck, /忽略/);
  assert.match(deck, /放回待办/);
  // 「已解决」是个空头承诺按钮：点一下状态就变了，网站上啥也没发生。
  // 真正能解决死链的只有设跳转，解决状态只该由系统在**实测跳转生效后**自动写。
  assert.doesNotMatch(deck, /已解决/);
  assert.doesNotMatch(deck, /"resolve"/);
  // 但 resolve 能力要留着——RedirectManager 验证通过后自动调它
  const panels = read("WpBridgePanels.tsx");
  assert.match(panels, /updateHealthFinding\(pendingFinding\.findingId, "resolve"\)/);
});

test("没保存就点验证，要说人话而不是甩一个 404", () => {
  const panels = read("WpBridgePanels.tsx");
  assert.match(panels, /还没保存/);
  assert.match(panels, /savedPaths/);
});

test("跳转表相关端点都在代理白名单里（这功能全靠它们）", async () => {
  const { isAllowedBackendProxyPath } = await import(
    "../../frontend/src/app/api/backend/[...path]/route.ts"
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["h", "wp", "redirects"]), true);
  assert.equal(isAllowedBackendProxyPath("PUT", ["h", "wp", "redirects"]), true);
  assert.equal(
    isAllowedBackendProxyPath("POST", ["h", "wp", "redirects", "verify"]),
    true,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["h", "findings"]), true);
});
