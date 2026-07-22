import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

const allowed = [
  ["GET", ["h", "wp", "redirects"]],
  ["PUT", ["h", "wp", "redirects"]],
  ["POST", ["h", "wp", "redirects", "verify"]],
  ["GET", ["h", "wp", "sentinel"]],
  ["POST", ["h", "wp", "smtp-check"]],
];

test("H WordPress bridge endpoints are registered in the exact proxy allowlist", () => {
  for (const [method, path] of allowed) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      true,
      `${method} /${path.join("/")}`,
    );
  }
});

test("H WordPress proxy rejects neighboring methods and wildcard paths", () => {
  const rejected = [
    ["POST", ["h", "wp", "redirects"]],
    ["DELETE", ["h", "wp", "redirects"]],
    ["GET", ["h", "wp", "redirects", "verify"]],
    ["POST", ["h", "wp", "sentinel"]],
    ["GET", ["h", "wp", "smtp-check"]],
    ["GET", ["h", "wp", "anything"]],
    ["POST", ["h", "wp", "smtp-check", "again"]],
  ];
  for (const [method, path] of rejected) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")}`,
    );
  }
});

test("H site-health workspace exposes redirect and sentinel operator controls", () => {
  const workspace = readFileSync(
    "frontend/src/modules/h/sitehealth/SiteHealthWorkspace.tsx",
    "utf8",
  );
  const panels = readFileSync(
    "frontend/src/modules/h/sitehealth/WpBridgePanels.tsx",
    "utf8",
  );
  const api = readFileSync(
    "frontend/src/modules/h/sitehealth/api.ts",
    "utf8",
  );

  assert.match(workspace, /跳转管理/);
  assert.match(workspace, /插件哨兵/);
  assert.match(panels, /站点桥断开/);
  assert.match(panels, /将执行一次真实邮箱登录/);
  assert.match(panels, /saveWpRedirects/);
  assert.match(panels, /verifyWpRedirect/);
  assert.match(api, /\/h\/wp\/redirects\/verify/);
  assert.match(api, /\/h\/wp\/smtp-check/);
  assert.doesNotMatch(panels, /password_masked/);
  assert.doesNotMatch(api, /password_masked/);
});

test("sentinel refresh and SMTP check remain separate explicit actions", () => {
  const panels = readFileSync(
    "frontend/src/modules/h/sitehealth/WpBridgePanels.tsx",
    "utf8",
  );
  const sentinelLoader = panels.match(
    /const load = useCallback[\s\S]*?useEffect\(\(\) => \{[\s\S]*?\}, \[load\]\);/g,
  );

  assert.ok(sentinelLoader && sentinelLoader.length >= 2);
  assert.match(panels, /setShowConfirmation\(true\)/);
  assert.match(panels, /runWpSmtpCheck\(\)/);
  assert.doesNotMatch(sentinelLoader.at(-1), /runWpSmtpCheck/);
});
