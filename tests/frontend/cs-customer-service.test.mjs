import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";
import { getCsNotificationTarget } from "../../frontend/src/modules/notifications/routing.ts";

const uuid = "01234567-89ab-4def-8123-456789abcdef";

test("CS management endpoints use the authenticated app proxy only", () => {
  const allowed = [
    ["GET", ["cs", "messages"]],
    ["GET", ["cs", "messages", uuid]],
    ["PATCH", ["cs", "messages", uuid]],
    ["POST", ["cs", "messages", uuid, "reply"]],
    ["GET", ["cs", "summary"]],
  ];
  for (const [method, path] of allowed) {
    assert.equal(isAllowedBackendProxyPath(method, path), true);
    assert.equal(
      getBackendApiPath(method, path),
      `/api/app/${path.join("/")}`,
    );
  }

  const denied = [
    ["POST", ["cs", "inbound"]],
    ["POST", ["cs", "messages"]],
    ["GET", ["cs", "messages", "not-a-uuid"]],
    ["POST", ["cs", "messages", "not-a-uuid", "reply"]],
    ["GET", ["cs", "messages", uuid, "reply"]],
    ["POST", ["cs", "messages", uuid, "reply", "extra"]],
    ["DELETE", ["cs", "messages", uuid]],
    ["PATCH", ["cs", "summary"]],
    ["GET", ["cs", "secrets"]],
  ];
  for (const [method, path] of denied) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")} must stay blocked`,
    );
  }
});

test("CS API client always scopes lists to exactly one team", () => {
  const apiSource = readFileSync(
    "frontend/src/modules/cs/customer-service/api.ts",
    "utf8",
  );
  assert.match(apiSource, /new URLSearchParams\(\{[\s\S]*channel,[\s\S]*page:/);
  assert.match(apiSource, /`\/cs\/messages\?\$\{params\.toString\(\)\}`/);
  assert.match(apiSource, /`\/cs\/messages\/\$\{encodeURIComponent\(messageId\)\}`/);
  assert.match(
    apiSource,
    /`\/cs\/messages\/\$\{encodeURIComponent\(messageId\)\}\/reply`/,
  );
  assert.match(apiSource, /retryLimit: 0/);
  assert.match(apiSource, /timeoutMs: 20_000/);
  assert.match(apiSource, /apiRequest<CSSummary>\("\/cs\/summary"/);
  assert.doesNotMatch(apiSource, /\/public\/cs\/inbound/);
});

test("CS page has two physical team tabs and the required service workflow", () => {
  const source = readFileSync(
    "frontend/src/modules/cs/customer-service/CustomerServiceDeck.tsx",
    "utf8",
  );
  const pageSource = readFileSync(
    "frontend/src/app/(console)/cs/customer-service/page.tsx",
    "utf8",
  );
  const layoutSource = readFileSync(
    "frontend/src/app/(console)/cs/layout.tsx",
    "utf8",
  );
  const globals = readFileSync("frontend/src/app/globals.css", "utf8");

  assert.match(source, /channel: "retail", label: "C端 · 零售咨询"/);
  assert.match(source, /channel: "wholesale", label: "B端 · 批发询盘"/);
  assert.doesNotMatch(source, /channel:\s*"all"/);
  assert.match(source, /summary\[entry\.channel\]\.new/);
  assert.match(source, /activeChannel === "wholesale" \? <th>公司<\/th>/);
  assert.match(source, /characters\.slice\(0, 40\)/);
  assert.match(source, /data-status=\{message\.status\}/);
  assert.match(source, /detail\.order_number/);
  assert.match(source, /detail\.company/);
  assert.match(source, /detail\.client_ip/);
  assert.match(source, /detail\.user_agent/);
  assert.match(source, /className="cs-conversation-line"/);
  assert.match(source, /cs-message-bubble-buyer/);
  assert.match(source, /cs-message-bubble-agent/);
  assert.match(source, /reply\.delivery_status === "sent"/);
  assert.match(source, /reply\.provider_note/);
  assert.match(source, /sendCSReply\(messageId, body\)/);
  assert.match(source, /setReplyBody\(""\)/);
  assert.match(source, /发送中/);
  assert.match(source, /发送回复/);
  assert.match(
    source,
    /买家的回信会送达 service@ 邮箱\(Titan\),暂不回流控制台/,
  );
  assert.match(source, /getCSMessage\(messageId\)/);
  assert.match(source, /updateCSMessage\(detail\.id/);
  assert.match(source, /\{ \.\.\.updated, replies: current\.replies \?\? \[\] \}/);
  assert.match(source, /internal_note: draftNote\.trim\(\) \|\| null/);
  assert.match(pageSource, /<h1>客服中心<\/h1>/);
  assert.match(layoutSource, /className="ra-command cs-command"/);
  assert.match(globals, /CS 客服中心 · 双分队收件箱/);
  assert.match(globals, /\.cs-status-badge\[data-status="spam"\]/);
  assert.match(globals, /\.cs-message-bubble-agent\[data-delivery="failed"\]/);
  assert.match(globals, /\.cs-delivery-badge\[data-delivery="failed"\]/);
  assert.match(globals, /\.cs-reply-toast/);
});

test("CS notifications resolve channel and message into a safe team deep link", () => {
  assert.deepEqual(
    getCsNotificationTarget({
      event_type: "cs.message_received",
      payload: {
        channel: "wholesale",
        message_id: uuid,
        route: `/cs/customer-service?channel=wholesale&message=${uuid}`,
      },
      source: "cs_customer_service",
    }),
    {
      channel: "wholesale",
      href: `/cs/customer-service?channel=wholesale&message=${uuid}`,
      messageId: uuid,
    },
  );
  assert.deepEqual(
    getCsNotificationTarget({
      event_type: "message_received",
      external_refs: {
        console_path: `/cs/customer-service?channel=retail&message=${uuid}`,
      },
      source: "cs.customer_service",
    }),
    {
      channel: "retail",
      href: `/cs/customer-service?channel=retail&message=${uuid}`,
      messageId: uuid,
    },
  );
  assert.deepEqual(
    getCsNotificationTarget({
      event_type: "cs.message_received",
      payload: { channel: "retail", message_id: uuid },
      source: "cs",
    }),
    {
      channel: "retail",
      href: `/cs/customer-service?channel=retail&message=${uuid}`,
      messageId: uuid,
    },
  );
  assert.equal(
    getCsNotificationTarget({
      event_type: "cs.message_received",
      payload: { channel: "all", message_id: uuid },
      source: "cs",
    }),
    null,
  );
  assert.equal(
    getCsNotificationTarget({
      payload: { route: `//evil.example/cs/customer-service?channel=retail&message=${uuid}` },
    }),
    null,
  );

  const inboxSource = readFileSync(
    "frontend/src/modules/notifications/NotificationInbox.tsx",
    "utf8",
  );
  assert.match(inboxSource, /getCsNotificationTarget\(item\)/);
  assert.match(inboxSource, /router\.push\(target\.href\)/);
  assert.match(inboxSource, /打开消息/);
});
