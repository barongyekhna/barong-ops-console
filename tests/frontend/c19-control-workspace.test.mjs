import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
  isAllowedC19Path,
  isBlockedC19InfrastructurePath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const allowed = [
  ["GET", ["c19", "directory"]],
  ["GET", ["c19", "profiles", "42"]],
  ["GET", ["c19", "friend-requests"]],
  ["POST", ["c19", "friend-requests"]],
  ["POST", ["c19", "friend-requests", "c19frq_0123456789abcdef0123456789abcdef", "accept"]],
  ["POST", ["c19", "friend-requests", "c19frq_0123456789abcdef0123456789abcdef", "reject"]],
  ["POST", ["c19", "friend-requests", "c19frq_0123456789abcdef0123456789abcdef", "cancel"]],
  ["GET", ["c19", "friends"]],
  ["DELETE", ["c19", "friends", "42"]],
  ["GET", ["c19", "blocks"]],
  ["POST", ["c19", "blocks", "42"]],
  ["DELETE", ["c19", "blocks", "42"]],
  ["GET", ["c19", "conversations"]],
  ["POST", ["c19", "conversations", "direct"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "settings"]],
  ["PATCH", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "settings"]],
  ["POST", ["c19", "groups"]],
  ["PATCH", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef"]],
  ["POST", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef", "members"]],
  ["DELETE", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef", "members", "42"]],
  ["POST", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef", "leave"]],
  ["POST", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef", "transfer-owner"]],
  ["DELETE", ["c19", "groups", "conv_0123456789abcdef0123456789abcdef"]],
  ["GET", ["c19", "events"]],
  ["GET", ["c19", "events", "tail"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "messages"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "messages"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "delivered"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "read"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "unread"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "resume"]],
];

test("C19 proxy exposes only the agreed control and chat-record methods", () => {
  for (const [method, path] of allowed) {
    assert.equal(isAllowedC19Path(method, path), true, `${method} /${path.join("/")}`);
    assert.equal(isAllowedBackendProxyPath(method, path), true);
    assert.equal(
      getBackendApiPath(method, path),
      `/api/app/${path.join("/")}`,
    );
  }
});

test("C19 proxy rejects unapproved methods and non-record content paths", () => {
  const denied = [
    ["POST", ["c19", "messages", "send"]],
    ["GET", ["c19", "messages", "conv_0123456789abcdef"]],
    ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "messages", "history"]],
    ["DELETE", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "messages"]],
    ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "delivered"]],
    ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "unread"]],
    ["POST", ["c19", "events"]],
    ["POST", ["c19", "events", "tail"]],
    ["POST", ["c19", "attachments", "upload"]],
    ["POST", ["c19", "moments"]],
    ["GET", ["c19", "moments", "feed"]],
    ["POST", ["c19", "calls", "voice"]],
    ["POST", ["c19", "calls", "video"]],
    ["DELETE", ["c19", "directory"]],
    ["PATCH", ["c19", "friends", "42"]],
    ["POST", ["c19", "profiles", "42"]],
    ["GET", ["c19", "profiles", "not-a-numeric-user"]],
  ];

  for (const [method, path] of denied) {
    assert.equal(isAllowedC19Path(method, path), false, `${method} /${path.join("/")}`);
    assert.equal(isAllowedBackendProxyPath(method, path), false);
    assert.equal(getBackendApiPath(method, path), null);
  }
});

test("C19 proxy explicitly isolates storage, VPS, provider, and secret paths", () => {
  const blocked = [
    ["c19", "storage"],
    ["c19", "providers"],
    ["c19", "vps"],
    ["c19", "configuration"],
    ["c19", "credentials"],
    ["c19", "chat-record-store"],
    ["c19", "chat-asset-store"],
    ["c19", "groups", "provider", "members"],
  ];

  for (const path of blocked) {
    assert.equal(isBlockedC19InfrastructurePath(path), true);
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(getBackendApiPath("GET", path), null);
  }
});

test("C19 workspace stays hidden and exposes only durable text or Emoji chat", () => {
  const navigationSource = readFileSync("frontend/src/lib/navigation.ts", "utf8");
  const pageSource = readFileSync(
    "frontend/src/app/(console)/c19/page.tsx",
    "utf8",
  );
  const apiSource = readFileSync("frontend/src/modules/c19/api.ts", "utf8");
  const typeSource = readFileSync("frontend/src/modules/c19/types.ts", "utf8");
  const workspaceSource = readFileSync(
    "frontend/src/modules/c19/C19Workspace.tsx",
    "utf8",
  );
  const chatSource = readFileSync(
    "frontend/src/modules/c19/C19ChatPanel.tsx",
    "utf8",
  );
  const recoverySource = readFileSync(
    "frontend/src/modules/c19/C19ChatRecovery.ts",
    "utf8",
  );

  assert.doesNotMatch(navigationSource, /\/c19|c19\.communication/i);
  assert.match(pageSource, /C19Workspace/);
  assert.match(workspaceSource, /文字与 Emoji 已接入可迁移的独立记录服务/);
  assert.match(workspaceSource, /图片、文件和朋友圈仍未开放/);
  assert.match(workspaceSource, /const LOAD_LIMIT = 100/);
  assert.match(workspaceSource, /getC19Profile\(user\.id\)/);
  assert.match(workspaceSource, /affiliations\.length === 1/);
  assert.match(workspaceSource, /多组织成员必须明确选择/);
  assert.match(workspaceSource, /actor_affiliation_id: actor\.affiliation_id/);
  assert.match(workspaceSource, /peer_affiliation_id: peer\.affiliation_id/);
  assert.match(apiSource, /conversationRuntimePath\(conversationId, "messages"\)/);
  assert.doesNotMatch(apiSource, /\/attachments|\/moments|\/storage|\/providers|\/vps/i);
  assert.match(apiSource, /params\.set\("search", query\.search\)/);
  assert.match(
    apiSource,
    /params\.set\("affiliation_org_id", query\.affiliation_org_id\)/,
  );
  assert.doesNotMatch(apiSource, /params\.set\("org_id"/);
  assert.match(typeSource, /peer_user_id: number/);
  assert.match(typeSource, /actor_affiliation_id\?: string/);
  assert.doesNotMatch(typeSource, /C19CreateDirectConversationInput = \{\s*actor:/);
  assert.doesNotMatch(workspaceSource, /createC19DirectConversation\(\{\s*actor:/);
  assert.doesNotMatch(`${workspaceSource}\n${chatSource}`, /type="file"/);
  assert.doesNotMatch(
    `${workspaceSource}\n${chatSource}`,
    />\s*(?:上传文件|发布朋友圈|语音通话|视频通话)\s*</,
  );
  assert.match(chatSource, /clientMessageId: makeClientMessageId\(\)/);
  assert.match(chatSource, /transmit\(retryMessage\)/);
  assert.match(chatSource, /不会制造重复消息/);
  assert.match(chatSource, /mergeC19MessageWindow/);
  assert.match(chatSource, /historyCursor/);
  assert.match(chatSource, /advanceC19Delivery/);
  assert.match(chatSource, /advanceC19Read/);
  assert.match(chatSource, /getC19UnreadPosition/);
  assert.match(chatSource, /getC19ResumePosition/);
  assert.match(chatSource, /const recoverFromResume = useCallback/);
  assert.match(chatSource, /forwardCursor: resume\.resume_cursor/);
  assert.match(chatSource, /initializeC19RecoveryWindow/);
  assert.match(chatSource, /drainC19ForwardRecoveryBatch/);
  assert.match(chatSource, /checkpoint\.forwardCursor = pageProgress\.nextCursor/);
  assert.match(chatSource, /recoveryCheckpointRef/);
  assert.match(chatSource, /RECOVERY_BATCH_PAGES = 20/);
  assert.match(chatSource, /window\.setTimeout\(resolve, 0\)/);
  assert.match(chatSource, /MAX_RENDERED_MESSAGES = 2_000/);
  assert.match(recoverySource, /sorted\.slice\(-maxRecords\)/);
  assert.match(chatSource, /recoveryReady \|\| isRecovering/);
  assert.match(chatSource, /safeReceiptSequence/);
  assert.match(chatSource, /drainEventPages/);
  assert.match(chatSource, /MAX_EVENT_DRAIN_PAGES/);
  assert.match(chatSource, /MAX_EVENT_DRAIN_PAGES = 50/);
  assert.match(chatSource, /SSE 必须返回带 next_cursor 的事件页/);
  assert.match(chatSource, /getC19MessageEventTail/);
  assert.match(chatSource, /ensureEventTailBoundary/);
  assert.doesNotMatch(chatSource, /drainEventPages\(null/);
  assert.match(typeSource, /C19MessageEventTail/);
  assert.match(chatSource, /new EventSource/);
  assert.match(chatSource, /listC19MessageEvents/);
  assert.match(chatSource, /HTTP 恢复模式/);
  assert.match(chatSource, /error\.status === 400 \|\| error\.status === 422/);
  assert.match(chatSource, /eventCursorRef\.current = null/);
  assert.match(chatSource, /sendInFlightRef/);
  assert.match(chatSource, /error instanceof ApiError && error\.status === 410/);
  assert.match(chatSource, /原 client_message_id 不能继续重放/);
  assert.match(chatSource, /contentTypeFor/);
  assert.match(typeSource, /C19MessageContentType = "text" \| "emoji"/);
  assert.doesNotMatch(chatSource, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(chatSource, /localStorage|sessionStorage|indexedDB/i);
  assert.doesNotMatch(chatSource, /FileReader|FormData|Blob|ArrayBuffer/);
});
