// 「版本更新」面板的守卫。
//
// 盯三件事：
// 1. 三处版本号必须一致 —— 后端 release_registry.py 是权威来源，
//    前端 release-metadata.ts 是手抄副本，面板首条又抄一次。
//    2026-09-02 之前这两份副本靠人手同步、漂了也没人知道（前端那份甚至
//    全仓零 import，是死代码）。这条断言把静默漂移变成测试期就报的错。
// 2. 浮层复用 OverlayModal，不是第六个自造轮子。
// 3. 顶栏按钮挂上去了 —— 「函数写好了没人调用」这个坑本轮已经栽过三次。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(path, "utf8");

// 前端构建容器里只 COPY 了 frontend/ 和 tests/frontend/（见 frontend/Dockerfile），
// **没有 backend/**。直接 read 后端文件会 ENOENT，让整份测试文件在构建时崩掉。
// 所以后端那份按「有就查、没有就跳过」处理：仓库根目录下（本地、CI 全量）
// 两棵树都在，一致性照查；容器里只验前端自身的自洽。
const readOptional = (path) => {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
};

const backendRegistry = readOptional("backend/app/core/release_registry.py");
const frontendMetadata = read("frontend/src/lib/release-metadata.ts");
const releaseNotes = read("frontend/src/components/release-notes.tsx");
const releaseButton = read("frontend/src/components/release-notes-button.tsx");
const shell = read("frontend/src/components/saas-shell.tsx");
const overlayModal = read("frontend/src/components/overlay-modal.tsx");
const overlayCss = read("frontend/src/components/overlay-modal.module.css");

test("版本号在后端与前端之间不许漂", (t) => {
  const frontend = frontendMetadata.match(
    /^export const RELEASE_VERSION = "([^"]+)";/m,
  );
  assert.ok(frontend, "前端 RELEASE_VERSION 没找到");

  // 备份脚本按这个正则校验版本号，格式不对会让备份中断。这条不依赖后端文件。
  assert.match(frontend[1], /^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$/);

  if (backendRegistry === null) {
    t.skip("构建容器里没有 backend/，跨端一致性在仓库根目录下才查");
    return;
  }

  const backend = backendRegistry.match(
    /^SYSTEM_RELEASE_VERSION:\s*Final\s*=\s*"([^"]+)"/m,
  );
  assert.ok(backend, "后端 SYSTEM_RELEASE_VERSION 没找到");
  assert.equal(
    frontend[1],
    backend[1],
    "前端 release-metadata.ts 与后端 release_registry.py 的版本号不一致",
  );
});

test("面板首条版本直接取自 release-metadata，不再手抄第三份", () => {
  assert.match(releaseNotes, /import \{ RELEASE_VERSION \} from "@\/lib\/release-metadata"/);
  assert.match(releaseNotes, /version: RELEASE_VERSION/);
});

test("面板内容是结构化数据，不注入 HTML", () => {
  // 匹配「真的用了」的形态（dangerouslySetInnerHTML={...}），
  // 而不是这个词出现在注释里 —— 文件头正好在解释为什么不用它。
  assert.doesNotMatch(releaseNotes, /dangerouslySetInnerHTML\s*=/);
  // 数据形状照 legal-content.tsx：类型 + 常量 + 渲染器
  assert.match(releaseNotes, /export const RELEASE_NOTES: ReleaseNote\[\]/);
  assert.match(releaseNotes, /export function ReleaseNotesView/);
});

test("每条更新都必须写明日期", () => {
  // 只看数据区。类型定义里也有 `version: string` / `date: string`，
  // 从整份文件里数会把它们一起数进去。
  const data = releaseNotes.slice(
    releaseNotes.indexOf("export const RELEASE_NOTES"),
  );
  const dates = data.match(/date: "\d{4}-\d{2}-\d{2}"/g) ?? [];
  const versions = data.match(/^\s+version: /gm) ?? [];
  assert.ok(dates.length > 0, "没有任何日期");
  assert.equal(
    dates.length,
    versions.length,
    "有版本条目没写日期 —— 更新记录不写日期就失去了大半价值",
  );
});

test("浮层复用 OverlayModal，不是第六个自造轮子", () => {
  assert.match(releaseButton, /import \{ OverlayModal \} from "\.\/overlay-modal"/);
  assert.match(releaseButton, /placement="drawer"/);
  // 长文档不能用小确认框那个组件：它没有 max-height、没有内部滚动、没有滚动锁
  assert.doesNotMatch(releaseButton, /OutboundConfirm/);
});

test("抽屉摆位是纯加法，居中摆位仍是默认", () => {
  assert.match(overlayModal, /placement = "center"/);
  assert.match(overlayCss, /\.overlayDrawer/);
  assert.match(overlayCss, /\.modalDrawer/);
  // 抽屉要占满高度，否则长报告会被压在中间一小块里
  assert.match(overlayCss, /height: 100dvh/);
});

test("按钮真的挂进了顶栏（写好了没人调用 = 没写）", () => {
  assert.match(shell, /import \{ ReleaseNotesButton \}/);
  assert.match(shell, /<ReleaseNotesButton \/>/);
  // 复用顶栏既有的按钮类，别新造一套全局样式
  assert.match(releaseButton, /className="secondary-button topbar-action"/);
});

test("面板是面向全体使用者的口径，不是内部工作汇报", () => {
  // 第一人称、对话式称呼、内部账号名都不该出现在产品里
  assert.doesNotMatch(releaseNotes, /我(修|做|发现|以为|倾向|犯)/);
  assert.doesNotMatch(releaseNotes, /QA0831/);
  assert.doesNotMatch(releaseNotes, /还欠你|你说|给你看/);
});
