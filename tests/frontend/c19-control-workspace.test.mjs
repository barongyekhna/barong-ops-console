import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
  isAllowedC19Path,
  isBlockedC19InfrastructurePath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const momentId = "mom_0123456789abcdef0123456789abcdef";
const commentId = "cmt_0123456789abcdef0123456789abcdef";
const assetId = "att_0123456789abcdef0123456789abcdef";

const allowed = [
  ["GET", ["c19", "directory"]],
  ["GET", ["c19", "profiles", "42"]],
  ["PATCH", ["c19", "profiles", "me"]],
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
  ["GET", ["c19", "unread"]],
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
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "assets", "upload-intents"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "assets", "att_0123456789abcdef0123456789abcdef"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "assets", "att_0123456789abcdef0123456789abcdef", "finalize"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "records", "record_01", "assets", "att_0123456789abcdef0123456789abcdef", "access-intents"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "delivered"]],
  ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "read"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "unread"]],
  ["GET", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "resume"]],
  ["POST", ["c19", "moments", "drafts"]],
  ["GET", ["c19", "moments", "feed"]],
  ["GET", ["c19", "moments", "events"]],
  ["GET", ["c19", "moments", "events", "tail"]],
  ["GET", ["c19", "moments", momentId]],
  ["DELETE", ["c19", "moments", momentId]],
  ["POST", ["c19", "moments", momentId, "publish"]],
  ["PUT", ["c19", "moments", momentId, "like"]],
  ["DELETE", ["c19", "moments", momentId, "like"]],
  ["GET", ["c19", "moments", momentId, "likes"]],
  ["GET", ["c19", "moments", momentId, "comments"]],
  ["POST", ["c19", "moments", momentId, "comments"]],
  ["DELETE", ["c19", "moments", momentId, "comments", commentId]],
  ["POST", ["c19", "moments", momentId, "assets", "upload-intents"]],
  ["GET", ["c19", "moments", momentId, "assets", assetId]],
  ["POST", ["c19", "moments", momentId, "assets", assetId, "finalize"]],
  ["POST", ["c19", "moments", momentId, "assets", assetId, "access-intents"]],
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
    ["POST", ["c19", "unread"]],
    ["GET", ["c19", "unread", "details"]],
    ["POST", ["c19", "attachments", "upload"]],
    ["GET", ["c19", "assets", "transfers", "authorize"]],
    ["PUT", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "assets", "att_0123456789abcdef0123456789abcdef"]],
    ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "assets", "not-an-asset", "finalize"]],
    ["POST", ["c19", "conversations", "conv_0123456789abcdef0123456789abcdef", "records", "bad/record", "assets", "att_0123456789abcdef0123456789abcdef", "access-intents"]],
    ["PUT", ["c19-assets", "u", "opaque-ticket"]],
    ["GET", ["c19-assets", "d", "opaque-ticket"]],
    ["POST", ["c19", "moments"]],
    ["PATCH", ["c19", "moments", momentId]],
    ["POST", ["c19", "moments", "not-a-moment", "publish"]],
    ["POST", ["c19", "moments", momentId, "likes"]],
    ["DELETE", ["c19", "moments", momentId, "comments", "not-a-comment"]],
    ["POST", ["c19", "moments", momentId, "assets", "not-an-asset", "finalize"]],
    ["GET", ["c19", "moments", "events", "anything"]],
    ["POST", ["c19", "calls", "voice"]],
    ["POST", ["c19", "calls", "video"]],
    ["DELETE", ["c19", "directory"]],
    ["PATCH", ["c19", "friends", "42"]],
    ["POST", ["c19", "profiles", "42"]],
    ["PATCH", ["c19", "profiles", "42"]],
    ["GET", ["c19", "profiles", "me"]],
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

test("C19 is a global authenticated feature with optional organization context", () => {
  const sidebarSource = readFileSync(
    "frontend/src/components/capability-sidebar-engine.tsx",
    "utf8",
  );
  const routeGuardSource = readFileSync(
    "frontend/src/components/permission-route-guard.tsx",
    "utf8",
  );
  const pageSource = readFileSync(
    "frontend/src/app/(console)/c19/page.tsx",
    "utf8",
  );
  const layoutSource = readFileSync(
    "frontend/src/app/(console)/c19/layout.tsx",
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
  const momentsSource = readFileSync(
    "frontend/src/modules/c19/C19MomentsPanel.tsx",
    "utf8",
  );
  const composerSource = readFileSync(
    "frontend/src/modules/c19/C19MomentComposer.tsx",
    "utf8",
  );
  const unreadSource = readFileSync(
    "frontend/src/modules/c19/C19UnreadStatus.tsx",
    "utf8",
  );

  assert.match(sidebarSource, /href="\/c19"/);
  // 前端界面不出现 C19 字样：侧边导航与页面只叫「通讯」。
  assert.match(sidebarSource, />通讯</);
  assert.doesNotMatch(sidebarSource, /C19 通讯/);
  assert.match(sidebarSource, /useC19UnreadCount/);
  assert.match(routeGuardSource, /pathname === "\/c19"/);
  assert.match(routeGuardSource, /isC19Route \|\|/);
  assert.match(pageSource, /C19Workspace/);
  assert.match(layoutSource, /className="ra-command"/);
  assert.match(layoutSource, /className="ra-command-space"/);
  assert.match(layoutSource, /className="ra-command-phoenix"/);
  assert.doesNotMatch(workspaceSource, /必须明确选择.*组织身份/);
  assert.doesNotMatch(workspaceSource, /朋友圈仍未开放/);
  assert.match(workspaceSource, /const LOAD_LIMIT = 100/);
  assert.match(workspaceSource, /getC19Profile\(user\.id\)/);
  assert.doesNotMatch(workspaceSource, /affiliations\.length === 1/);
  // 微信式动线：点名字直接开聊，永远使用基础通讯身份，
  // 界面上不存在任何组织身份选择器。
  assert.match(
    workspaceSource,
    /createC19DirectConversation\(\{\s*peer_user_id: profile\.user_id,\s*\}\)/,
  );
  assert.doesNotMatch(
    workspaceSource,
    /actor_affiliation_id|peer_affiliation_id|IdentitySelect/,
  );
  assert.doesNotMatch(workspaceSource, /affiliation_id:/);
  assert.match(workspaceSource, /adoptConversation\(conversation\)/);
  assert.match(workspaceSource, /getC19UnreadPosition/);
  assert.match(workspaceSource, /listC19MessageHistory\(conversationId, \{ limit: 1 \}\)/);
  assert.match(workspaceSource, /C19_UNREAD_CHANGED_EVENT/);
  assert.match(workspaceSource, /direct_peer\?\.display_name/);
  assert.match(workspaceSource, /的群聊/);
  assert.match(workspaceSource, /disabled=\{Boolean\(busyKey\)\}/);

  // 名片：组织身份只读展示，不是选择器；主动作是「发消息」。
  const profileCardSource = readFileSync(
    "frontend/src/modules/c19/C19ProfileCard.tsx",
    "utf8",
  );
  const avatarSource = readFileSync(
    "frontend/src/modules/c19/C19Avatar.tsx",
    "utf8",
  );
  assert.match(profileCardSource, /发消息/);
  assert.match(profileCardSource, /profile\.affiliations\.map/);
  assert.doesNotMatch(
    profileCardSource,
    /<select|actor_affiliation_id|peer_affiliation_id/,
  );
  assert.match(profileCardSource, /基础通讯用户 · 未加入任何组织/);
  assert.match(profileCardSource, /更换头像/);
  assert.match(profileCardSource, /恢复默认/);
  assert.match(profileCardSource, /onUpdateAvatar\(normalized \|\| null\)/);
  assert.match(avatarSource, /onError=\{\(\) => setImageFailed\(true\)\}/);
  assert.match(avatarSource, /referrerPolicy="no-referrer"/);
  assert.match(apiSource, /updateC19MyProfile/);
  assert.match(apiSource, /`\$\{C19_API_BASE\}\/profiles\/me`/);
  assert.match(apiSource, /conversationRuntimePath\(conversationId, "messages"\)/);
  assert.doesNotMatch(apiSource, /\/attachments|\/storage|\/providers|\/vps/i);
  assert.match(apiSource, /createC19MomentDraft/);
  assert.match(apiSource, /listC19MomentFeed/);
  assert.match(apiSource, /params\.set\("search", query\.search\)/);
  assert.match(
    apiSource,
    /params\.set\("affiliation_org_id", query\.affiliation_org_id\)/,
  );
  assert.doesNotMatch(apiSource, /params\.set\("org_id"/);
  assert.match(typeSource, /peer_user_id: number/);
  assert.match(typeSource, /actor_affiliation_id\?: string/);
  assert.match(typeSource, /C19ParticipantInput = \{\s*user_id: number;\s*affiliation_id\?: string;/);
  assert.match(typeSource, /actor_org_id: string \| null/);
  assert.match(typeSource, /direct_peer\?: C19DirectPeer \| null/);
  assert.doesNotMatch(typeSource, /C19CreateDirectConversationInput = \{\s*actor:/);
  assert.doesNotMatch(workspaceSource, /createC19DirectConversation\(\{\s*actor:/);
  assert.match(chatSource, /type="file"/);
  assert.match(composerSource, /发布朋友圈/);
  assert.doesNotMatch(
    `${workspaceSource}\n${chatSource}\n${momentsSource}`,
    />\s*(?:语音通话|视频通话)\s*</,
  );
  assert.match(chatSource, /clientMessageId: makeClientMessageId\(\)/);
  assert.match(chatSource, /transmit\(retryMessage\)/);
  assert.match(chatSource, /不会制造重复消息/);
  assert.match(chatSource, /mergeC19MessageWindow/);
  assert.match(chatSource, /historyCursor/);
  assert.match(chatSource, /advanceC19Delivery/);
  assert.match(chatSource, /advanceC19Read/);
  assert.match(chatSource, /announceC19UnreadChanged\(\)/);
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
  assert.match(chatSource, /EMOJI_CATEGORIES/);
  assert.match(chatSource, /aria-label="打开表情选择器"/);
  assert.match(chatSource, /aria-label="选择表情"/);
  assert.match(chatSource, /insertEmoji\(emoji\)/);
  assert.match(chatSource, /document\.addEventListener\("pointerdown", closeOnOutsideClick\)/);
  assert.match(typeSource, /C19MessageContentType = "text" \| "emoji" \| "image" \| "file"/);
  assert.match(typeSource, /assets: C19AssetReference\[\]/);
  assert.match(chatSource, /putC19AssetBytes/);
  assert.match(chatSource, /sha256C19File/);
  assert.match(chatSource, /URL\.createObjectURL/);
  assert.match(chatSource, /URL\.revokeObjectURL/);
  assert.match(chatSource, /pagehide/);
  assert.match(chatSource, /renderWindowMode === "older"/);
  assert.doesNotMatch(chatSource, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(chatSource, /localStorage|sessionStorage|indexedDB/i);
  assert.doesNotMatch(chatSource, /FileReader|FormData|Blob|ArrayBuffer/);
  assert.match(unreadSource, /getC19UnreadSummary/);
  assert.match(unreadSource, /summary\.total_unread_count/);
  assert.match(unreadSource, /Number\.isSafeInteger\(summary\.total_unread_count\)/);
  assert.match(unreadSource, /summary\.unread_conversation_count/);
  assert.doesNotMatch(unreadSource, /listC19Conversations|getC19UnreadPosition/);
  assert.match(unreadSource, /C19_UNREAD_POLL_INTERVAL_MS = 30_000/);
  assert.match(unreadSource, /activeControllerRef\.current\?\.abort\(\)/);
  assert.doesNotMatch(unreadSource, /localStorage|sessionStorage|indexedDB/);
});
