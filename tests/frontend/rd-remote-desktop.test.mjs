import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  LIVE_SESSION_STATES,
  deviceStatusLabel,
  normalizeRdDevice,
  normalizeRdDeviceDetail,
  normalizeRdDeviceList,
  normalizeRdIceConfig,
  normalizeRdSession,
  normalizeRdSessionList,
  platformLabel,
  toIceServers,
} from "../../frontend/src/modules/rd/types.ts";
import {
  encodeInputEvent,
  normalizePointer,
  parseInputEvent,
} from "../../frontend/src/modules/rd/input-protocol.ts";
import { getRdNativeBridge } from "../../frontend/src/modules/rd/native.ts";

const DEVICE_ID = "2f6fcb65-b51f-4b29-bc65-85f71437c2ac";
const SESSION_ID = "8c2b1a70-0f3d-4a55-9f21-6d0a5e8b7c34";

function device(overrides = {}) {
  return {
    agent_version: "0.4.0-pilot",
    busy: false,
    id: DEVICE_ID,
    is_mine: false,
    is_online: true,
    is_unattended: false,
    last_seen_at: "2026-09-11T10:00:00Z",
    name: "车间工位机",
    needs_consent: true,
    owner_name: "吴雨潼",
    owner_user_id: 169,
    platform: "win32",
    ...overrides,
  };
}

function session(overrides = {}) {
  return {
    consent_mode: "prompt",
    controller_name: "老板",
    controller_user_id: 1,
    device_id: DEVICE_ID,
    device_name: "车间工位机",
    end_reason: null,
    ended_at: null,
    id: SESSION_ID,
    requested_at: "2026-09-11T10:00:00Z",
    responded_at: null,
    started_at: null,
    state: "requested",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 规范化:后端少给一个字段不能让面板白屏
// ---------------------------------------------------------------------------
test("normalizeRdDevice accepts a complete device", () => {
  const parsed = normalizeRdDevice(device());
  assert.equal(parsed?.name, "车间工位机");
  assert.equal(parsed?.owner_user_id, 169);
});

test("normalizeRdDevice rejects malformed payloads outright", () => {
  for (const bad of [null, undefined, 42, "device", [], {}]) {
    assert.equal(normalizeRdDevice(bad), null);
  }
  assert.equal(normalizeRdDevice(device({ id: "" })), null);
  assert.equal(normalizeRdDevice(device({ owner_user_id: "169" })), null);
});

test("missing needs_consent falls back to requiring consent", () => {
  // 拿不准就走更严的那条路。默认放行是这类功能最危险的缺省值。
  const raw = device();
  delete raw.needs_consent;
  assert.equal(normalizeRdDevice(raw)?.needs_consent, true);
  assert.equal(normalizeRdDevice(device({ needs_consent: false }))?.needs_consent, false);
});

test("normalizeRdDeviceList drops bad rows instead of the whole list", () => {
  const parsed = normalizeRdDeviceList([device(), null, device({ id: "" })]);
  assert.equal(parsed.length, 1);
  assert.equal(normalizeRdDeviceList("nope").length, 0);
});

test("normalizeRdDeviceDetail keeps only well-formed grants", () => {
  const parsed = normalizeRdDeviceDetail({
    ...device(),
    grants: [
      { created_at: "2026-09-11T10:00:00Z", grantee_name: "殷承岳", grantee_user_id: 174 },
      { grantee_user_id: "174" },
      null,
    ],
  });
  assert.equal(parsed?.grants.length, 1);
  assert.equal(parsed?.grants[0].grantee_user_id, 174);
});

test("normalizeRdSession refuses unknown states and consent modes", () => {
  assert.equal(normalizeRdSession(session())?.state, "requested");
  assert.equal(normalizeRdSession(session({ state: "hijacked" })), null);
  assert.equal(normalizeRdSession(session({ consent_mode: "silent" })), null);
  assert.equal(normalizeRdSession(session({ controller_user_id: null })), null);
});

test("normalizeRdSessionList tolerates junk entries", () => {
  assert.equal(normalizeRdSessionList([session(), "junk", null]).length, 1);
});

test("live session states cover exactly the three occupying states", () => {
  assert.deepEqual(
    [...LIVE_SESSION_STATES].sort(),
    ["active", "consented", "requested"],
  );
});

// ---------------------------------------------------------------------------
// 通路配置:凑不齐的 TURN 凭据绝不发出去
// ---------------------------------------------------------------------------
test("toIceServers keeps STUN and complete TURN entries", () => {
  const servers = toIceServers(
    normalizeRdIceConfig({
      stun_urls: ["stun:stun.l.google.com:19302"],
      ttl: 600,
      turn_credential: "hmac",
      turn_urls: ["turn:1.2.3.4:3478"],
      turn_username: "1757600000:session",
    }),
  );
  assert.equal(servers.length, 2);
  assert.equal(servers[1].username, "1757600000:session");
});

test("toIceServers drops TURN when the credential triple is incomplete", () => {
  // 宁可连不上,也不把一把不完整的凭据递出去
  const servers = toIceServers(
    normalizeRdIceConfig({
      stun_urls: ["stun:stun.l.google.com:19302"],
      turn_credential: null,
      turn_urls: ["turn:1.2.3.4:3478"],
      turn_username: "1757600000:session",
    }),
  );
  assert.equal(servers.length, 1);
});

test("normalizeRdIceConfig survives a totally empty answer", () => {
  const config = normalizeRdIceConfig(null);
  assert.deepEqual(config.stun_urls, []);
  assert.deepEqual(toIceServers(config), []);
});

// ---------------------------------------------------------------------------
// 键鼠协议
// ---------------------------------------------------------------------------
test("normalizePointer maps to 0..1 and clamps outside the frame", () => {
  const rect = { height: 200, left: 100, top: 50, width: 400 };
  assert.deepEqual(normalizePointer({ clientX: 300, clientY: 150 }, rect), {
    x: 0.5,
    y: 0.5,
  });
  assert.deepEqual(normalizePointer({ clientX: -900, clientY: 9000 }, rect), {
    x: 0,
    y: 1,
  });
});

test("normalizePointer refuses to divide by a zero-sized frame", () => {
  assert.deepEqual(
    normalizePointer({ clientX: 10, clientY: 10 }, { height: 0, left: 0, top: 0, width: 0 }),
    { x: 0, y: 0 },
  );
});

test("parseInputEvent accepts the documented shapes", () => {
  assert.deepEqual(parseInputEvent('{"t":"m","x":0.25,"y":0.75}'), {
    t: "m",
    x: 0.25,
    y: 0.75,
  });
  assert.deepEqual(parseInputEvent('{"t":"d","b":0,"x":0.1,"y":0.2}'), {
    b: 0,
    t: "d",
    x: 0.1,
    y: 0.2,
  });
  assert.deepEqual(parseInputEvent('{"t":"k","c":"KeyA","d":true}'), {
    c: "KeyA",
    d: true,
    t: "k",
  });
});

test("parseInputEvent rejects anything it does not fully recognise", () => {
  for (const bad of [
    null,
    "",
    "not json",
    '{"t":"zzz"}',
    '{"t":"m","x":"0.5","y":0.5}',
    '{"t":"d","b":9,"x":0.1,"y":0.1}',
    '{"t":"k","c":"KeyA"}',
    '{"t":"s","s":""}',
  ]) {
    assert.equal(parseInputEvent(bad), null, `应当拒绝: ${String(bad)}`);
  }
});

test("key codes are restricted to plain alphanumerics", () => {
  // 被控端照着这个字段注入按键,放任意字符进来等于把一个注入面白送出去
  assert.equal(parseInputEvent('{"t":"k","c":"Key A","d":true}'), null);
  assert.equal(parseInputEvent('{"t":"k","c":"a;rm -rf","d":true}'), null);
  assert.equal(parseInputEvent(`{"t":"k","c":"${"A".repeat(33)}","d":true}`), null);
});

test("encodeInputEvent round-trips through parseInputEvent", () => {
  const event = { dx: -12.5, dy: 40, t: "w" };
  assert.deepEqual(parseInputEvent(encodeInputEvent(event)), event);
});

// ---------------------------------------------------------------------------
// 展示
// ---------------------------------------------------------------------------
test("device status prefers offline, then busy", () => {
  assert.equal(deviceStatusLabel(device({ is_online: false, busy: true })), "离线");
  assert.equal(deviceStatusLabel(device({ busy: true })), "正被远程");
  assert.equal(deviceStatusLabel(device()), "在线");
  assert.equal(platformLabel("win32"), "Windows");
  assert.equal(platformLabel("plan9"), "plan9");
});

// ---------------------------------------------------------------------------
// 原生桥检测:半截桥比没有桥更危险
// ---------------------------------------------------------------------------
const FULL_BRIDGE = {
  beginUnattended() {},
  consent() {},
  input() {},
  markUnattended() {},
  status() {},
  stop() {},
};

test("no window means no bridge", () => {
  assert.equal(getRdNativeBridge(), null);
});

test("a complete bridge is accepted, a partial one never is", (t) => {
  global.window = { barongRemote: { ...FULL_BRIDGE } };
  t.after(() => {
    delete global.window;
  });
  assert.notEqual(getRdNativeBridge(), null);

  for (const missing of Object.keys(FULL_BRIDGE)) {
    const partial = { ...FULL_BRIDGE };
    delete partial[missing];
    global.window = { barongRemote: partial };
    assert.equal(getRdNativeBridge(), null, `缺 ${missing} 时不该认`);
  }

  for (const junk of [null, undefined, "bridge", 42, []]) {
    global.window = { barongRemote: junk };
    assert.equal(getRdNativeBridge(), null);
  }
});

// ---------------------------------------------------------------------------
// 源码断言:结构和安全约束不能被以后顺手改掉
// ---------------------------------------------------------------------------
const dashboard = readFileSync(
  "frontend/src/modules/rd/RemoteDesktopDashboard.tsx",
  "utf8",
);
const viewer = readFileSync("frontend/src/modules/rd/RemoteViewer.tsx", "utf8");
const nginxRd = readFileSync("deploy/nginx/rd-locations.conf", "utf8");
const nginxTemplate = readFileSync(
  "deploy/nginx/ops.barongyekhna.com.conf.template",
  "utf8",
);

test("dashboard keeps the command-center shell", () => {
  assert.match(dashboard, /className="dashboard-page cc-dash cc-rd"/);
  assert.match(dashboard, /<DashboardScene \/>/);
  assert.doesNotMatch(dashboard, /\.module\.css/);
  assert.doesNotMatch(viewer, /\.module\.css/);
});

test("the web UI can deny but must never approve a control request", () => {
  // 整件事的地基:同意只能在被控机上那个原生框里点。网页上出现一个「同意」按钮,
  // 就等于把「人必须在机器跟前」这条保证作废。这条断言是防止它被顺手加回来。
  assert.match(dashboard, /respondRdSession\(target\.id, false\)/);
  assert.doesNotMatch(dashboard, /respondRdSession\([^)]*,\s*true\s*\)/);
  assert.doesNotMatch(dashboard, />\s*同意\s*</);
});

test("viewer sends normalized coordinates, never raw pixels", () => {
  assert.match(viewer, /normalizePointer/);
  assert.doesNotMatch(viewer, /screenX|screenY/);
});

test("Esc always releases the keyboard locally", () => {
  assert.match(viewer, /event\.key === "Escape"/);
});

test("nginx does not buffer the remote-desktop signalling stream", () => {
  // 断言真正被线上 include 的那份文件,不是仅供参考的模板
  assert.match(nginxRd, /location = \/api\/backend\/rd\/stream/);
  assert.match(nginxRd, /proxy_buffering off;/);
  assert.match(nginxRd, /proxy_cache off;/);
  // 模板只该引用它,不该再抄一份(两处维护必然漂移)
  assert.match(nginxTemplate, /include .*rd-locations\.conf;/);
  assert.doesNotMatch(nginxTemplate, /location = \/api\/backend\/rd\/stream/);
});

const agentSource = readFileSync("frontend/src/modules/rd/agent.ts", "utf8");

test("the controlled side validates every input before handing it to the injector", () => {
  // 往下递的结果是在别人电脑上真的按下去,所以没验过的一条都不能过
  assert.match(agentSource, /const parsed = parseInputEvent\(message\.data\);/);
  assert.match(agentSource, /if \(!parsed\) \{\s*\n\s*this\.droppedInputs \+= 1;\s*\n\s*return;/);
});

test("the controlled side only accepts the one named data channel", () => {
  assert.match(agentSource, /event\.channel\.label !== "input"/);
});

test("the controlled side never asks for a screen source id itself", () => {
  // 屏幕给不给由主进程的 display-media 处理器决定,网页只是调用方
  assert.match(agentSource, /navigator\.mediaDevices\.getDisplayMedia/);
  assert.doesNotMatch(agentSource, /chromeMediaSourceId|desktopCapturer/);
});

test("CSP lets WebRTC reach the ICE servers at all", () => {
  // connect-src 同时管 RTCPeerConnection 的 ICE 服务器地址。少了这几条,远程桌面
  // 会在同一局域网内能连、一出网就失败,而且浏览器不报明显错误。这条断言防止有人
  // 收紧 CSP 时顺手把它们删掉。
  const config = readFileSync("frontend/next.config.ts", "utf8");
  const block = config.slice(
    config.indexOf("connect-src 'self'"),
    config.indexOf("frame-src"),
  );
  assert.match(block, /stun:/, "CSP 里没有 stun: 地址");
  assert.match(block, /turn:/, "CSP 里没有 turn: 地址");
  // 换节点时必须两处一起改,注释里要留着这条提醒
  assert.match(config, /RD_TURN_URLS/);
});
