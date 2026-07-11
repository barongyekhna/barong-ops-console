import { apiRequest } from "@/lib/api";

import type {
  C19Block,
  C19Conversation,
  C19ConversationSummary,
  C19ConversationSettings,
  C19CreateDirectConversationInput,
  C19CreateFriendRequestInput,
  C19CreateGroupInput,
  C19DirectoryQuery,
  C19Friend,
  C19FriendRequest,
  C19GroupDeleteResponse,
  C19GroupLeaveResponse,
  C19ListQuery,
  C19MessageEventPage,
  C19MessageEventTail,
  C19MessageHistoryPage,
  C19MessageRecord,
  C19Page,
  C19Profile,
  C19ReceiptPosition,
  C19RelationshipMutation,
  C19ResumePosition,
  C19SendMessageInput,
  C19TransferGroupOwnerInput,
  C19UnreadPosition,
  C19UpdateConversationSettingsInput,
  C19UpdateGroupInput,
  C19AddGroupMembersInput,
} from "./types";

const C19_API_BASE = "/c19";
const C19_EVENT_PROXY_PATH = "/api/backend/c19/events";

function pageQuery(query: C19DirectoryQuery | C19ListQuery = {}) {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  if ("search" in query && query.search) params.set("search", query.search);
  if ("affiliation_org_id" in query && query.affiliation_org_id) {
    params.set("affiliation_org_id", query.affiliation_org_id);
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function listC19Directory(query: C19DirectoryQuery = {}) {
  return apiRequest<C19Page<C19Profile>>(
    `${C19_API_BASE}/directory${pageQuery(query)}`,
    { method: "GET" },
  );
}

export function getC19Profile(userId: number) {
  return apiRequest<C19Profile>(`${C19_API_BASE}/profiles/${userId}`, {
    method: "GET",
  });
}

export function listC19FriendRequests(query: C19ListQuery = {}) {
  return apiRequest<C19Page<C19FriendRequest>>(
    `${C19_API_BASE}/friend-requests${pageQuery(query)}`,
    { method: "GET" },
  );
}

export function createC19FriendRequest(input: C19CreateFriendRequestInput) {
  return apiRequest<C19FriendRequest>(`${C19_API_BASE}/friend-requests`, {
    body: input,
    method: "POST",
    retryLimit: 0,
  });
}

export function actOnC19FriendRequest(
  requestId: string,
  action: "accept" | "reject" | "cancel",
) {
  return apiRequest<C19FriendRequest>(
    `${C19_API_BASE}/friend-requests/${encodeURIComponent(requestId)}/${action}`,
    { method: "POST", retryLimit: 0 },
  );
}

export function listC19Friends(query: C19ListQuery = {}) {
  return apiRequest<C19Page<C19Friend>>(
    `${C19_API_BASE}/friends${pageQuery(query)}`,
    { method: "GET" },
  );
}

export function removeC19Friend(userId: number) {
  return apiRequest<C19RelationshipMutation>(`${C19_API_BASE}/friends/${userId}`, {
    method: "DELETE",
    retryLimit: 0,
  });
}

export function listC19Blocks(query: C19ListQuery = {}) {
  return apiRequest<C19Page<C19Block>>(
    `${C19_API_BASE}/blocks${pageQuery(query)}`,
    { method: "GET" },
  );
}

export function createC19Block(userId: number) {
  return apiRequest<C19Block>(`${C19_API_BASE}/blocks/${userId}`, {
    method: "POST",
    retryLimit: 0,
  });
}

export function removeC19Block(userId: number) {
  return apiRequest<C19RelationshipMutation>(`${C19_API_BASE}/blocks/${userId}`, {
    method: "DELETE",
    retryLimit: 0,
  });
}

export function listC19Conversations(query: C19ListQuery = {}) {
  return apiRequest<C19Page<C19ConversationSummary>>(
    `${C19_API_BASE}/conversations${pageQuery(query)}`,
    { method: "GET" },
  );
}

export function getC19Conversation(conversationId: string) {
  return apiRequest<C19Conversation>(
    `${C19_API_BASE}/conversations/${encodeURIComponent(conversationId)}`,
    { method: "GET" },
  );
}

export function createC19DirectConversation(
  input: C19CreateDirectConversationInput,
) {
  return apiRequest<C19Conversation>(`${C19_API_BASE}/conversations/direct`, {
    body: input,
    method: "POST",
    retryLimit: 0,
  });
}

export function getC19ConversationSettings(conversationId: string) {
  return apiRequest<C19ConversationSettings>(
    `${C19_API_BASE}/conversations/${encodeURIComponent(conversationId)}/settings`,
    { method: "GET" },
  );
}

export function updateC19ConversationSettings(
  conversationId: string,
  input: C19UpdateConversationSettingsInput,
) {
  return apiRequest<C19ConversationSettings>(
    `${C19_API_BASE}/conversations/${encodeURIComponent(conversationId)}/settings`,
    { body: input, method: "PATCH", retryLimit: 0 },
  );
}

export function createC19Group(input: C19CreateGroupInput) {
  return apiRequest<C19Conversation>(`${C19_API_BASE}/groups`, {
    body: input,
    method: "POST",
    retryLimit: 0,
  });
}

export function updateC19Group(
  conversationId: string,
  input: C19UpdateGroupInput,
) {
  return apiRequest<C19Conversation>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}`,
    { body: input, method: "PATCH", retryLimit: 0 },
  );
}

export function addC19GroupMembers(
  conversationId: string,
  input: C19AddGroupMembersInput,
) {
  return apiRequest<C19Conversation>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}/members`,
    { body: input, method: "POST", retryLimit: 0 },
  );
}

export function removeC19GroupMember(
  conversationId: string,
  userId: number,
) {
  return apiRequest<C19Conversation>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}/members/${userId}`,
    { method: "DELETE", retryLimit: 0 },
  );
}

export function leaveC19Group(conversationId: string) {
  return apiRequest<C19GroupLeaveResponse>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}/leave`,
    { method: "POST", retryLimit: 0 },
  );
}

export function transferC19GroupOwner(
  conversationId: string,
  input: C19TransferGroupOwnerInput,
) {
  return apiRequest<C19Conversation>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}/transfer-owner`,
    { body: input, method: "POST", retryLimit: 0 },
  );
}

export function dissolveC19Group(conversationId: string) {
  return apiRequest<C19GroupDeleteResponse>(
    `${C19_API_BASE}/groups/${encodeURIComponent(conversationId)}`,
    { method: "DELETE", retryLimit: 0 },
  );
}

function conversationRuntimePath(conversationId: string, resource: string) {
  return `${C19_API_BASE}/conversations/${encodeURIComponent(conversationId)}/${resource}`;
}

export function listC19MessageHistory(
  conversationId: string,
  query: { cursor?: string | null; limit?: number } = {},
) {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);
  const serialized = params.toString();
  return apiRequest<C19MessageHistoryPage>(
    `${conversationRuntimePath(conversationId, "messages")}${
      serialized ? `?${serialized}` : ""
    }`,
    { bypassCache: true, method: "GET", retryLimit: 1 },
  );
}

export function sendC19Message(
  conversationId: string,
  input: C19SendMessageInput,
) {
  return apiRequest<C19MessageRecord>(
    conversationRuntimePath(conversationId, "messages"),
    {
      body: input,
      method: "POST",
      retryLimit: 0,
    },
  );
}

function advanceC19Position(
  conversationId: string,
  resource: "delivered" | "read",
  throughSequence: number,
) {
  return apiRequest<C19ReceiptPosition>(
    conversationRuntimePath(conversationId, resource),
    {
      body: {
        through_sequence: throughSequence,
      },
      method: "POST",
      retryLimit: 0,
    },
  );
}

export function advanceC19Delivery(
  conversationId: string,
  throughSequence: number,
) {
  return advanceC19Position(conversationId, "delivered", throughSequence);
}

export function advanceC19Read(
  conversationId: string,
  throughSequence: number,
) {
  return advanceC19Position(conversationId, "read", throughSequence);
}

export function getC19UnreadPosition(conversationId: string) {
  return apiRequest<C19UnreadPosition>(
    conversationRuntimePath(conversationId, "unread"),
    { bypassCache: true, method: "GET", retryLimit: 1 },
  );
}

export function getC19ResumePosition(conversationId: string) {
  return apiRequest<C19ResumePosition>(
    conversationRuntimePath(conversationId, "resume"),
    { bypassCache: true, method: "GET", retryLimit: 1 },
  );
}

export function listC19MessageEvents(
  query: { cursor?: string | null; limit?: number } = {},
) {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);
  const serialized = params.toString();
  return apiRequest<C19MessageEventPage>(
    `${C19_API_BASE}/events${serialized ? `?${serialized}` : ""}`,
    { bypassCache: true, method: "GET", retryLimit: 1 },
  );
}

export function getC19MessageEventTail() {
  return apiRequest<C19MessageEventTail>(`${C19_API_BASE}/events/tail`, {
    bypassCache: true,
    method: "GET",
    retryLimit: 1,
  });
}

export function c19EventStreamUrl(cursor?: string | null) {
  if (!cursor) return C19_EVENT_PROXY_PATH;
  const params = new URLSearchParams({ cursor });
  return `${C19_EVENT_PROXY_PATH}?${params.toString()}`;
}
