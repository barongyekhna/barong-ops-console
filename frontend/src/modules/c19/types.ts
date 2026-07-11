export type C19Affiliation = {
  affiliation_id: string;
  org_id: string;
  org_name: string;
  org_type: string;
  role: "owner" | "admin" | "member" | string;
  joined_at: string;
};

export type C19Profile = {
  user_id: number;
  display_name: string;
  avatar_ref: string | null;
  bio: string | null;
  affiliations: C19Affiliation[];
  created_at?: string;
  updated_at?: string;
};

export type C19Page<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
};

export type C19ProfileSummary = {
  user_id: number;
  display_name: string;
  avatar_ref: string | null;
};

export type C19FriendRequestStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "cancelled";

export type C19FriendRequest = {
  request_id: string;
  requester: C19ProfileSummary;
  addressee: C19ProfileSummary;
  status: C19FriendRequestStatus;
  request_message: string | null;
  responded_at: string | null;
  created_at: string;
  updated_at: string;
};

export type C19Friend = {
  relationship_id: string;
  profile: C19Profile;
  established_at: string | null;
  created_at?: string;
  updated_at?: string;
};

export type C19Block = {
  block_id: string;
  profile: C19Profile;
  blocked_at: string;
};

export type C19RelationshipMutation = {
  user_id: number;
  changed: boolean;
};

export type C19ConversationType = "direct" | "group";
export type C19ConversationStatus = "active" | "archived" | "closed";
export type C19ConversationMemberRole = "owner" | "admin" | "member";
export type C19ConversationMemberStatus =
  | "invited"
  | "active"
  | "left"
  | "removed"
  | "banned";

export type C19ConversationMember = {
  affiliation_id: string;
  user_id: number;
  org_id: string;
  role: C19ConversationMemberRole;
  status: C19ConversationMemberStatus;
  joined_at: string;
  left_at: string | null;
};

export type C19ConversationSettings = {
  conversation_id: string;
  user_id: number;
  is_pinned: boolean;
  is_muted: boolean;
  is_archived: boolean;
  notification_level: "all" | "mentions" | "none";
  created_at?: string;
  updated_at?: string;
};

export type C19Conversation = {
  conversation_id: string;
  type: C19ConversationType;
  title: string | null;
  created_by_user_id: number | null;
  status: C19ConversationStatus;
  members: C19ConversationMember[];
  settings: C19ConversationSettings;
  created_at: string;
  updated_at: string;
};

export type C19ConversationSummary = {
  conversation_id: string;
  type: C19ConversationType;
  title: string | null;
  status: C19ConversationStatus;
  actor_role: C19ConversationMemberRole;
  actor_org_id: string;
  active_member_count: number;
  settings: C19ConversationSettings;
  created_at: string;
  updated_at: string;
};

export type C19GroupDeleteResponse = {
  conversation_id: string;
  status: "closed";
};

export type C19GroupLeaveResponse = {
  conversation_id: string;
  member_status: "left";
  conversation_status: "active";
};

export type C19ParticipantInput = {
  user_id: number;
  affiliation_id: string;
};

export type C19DirectoryQuery = {
  limit?: number;
  offset?: number;
  search?: string;
  affiliation_org_id?: string;
};

export type C19ListQuery = {
  limit?: number;
  offset?: number;
};

export type C19CreateFriendRequestInput = {
  addressee_user_id: number;
  request_message?: string;
};

export type C19CreateDirectConversationInput = {
  peer_user_id: number;
  actor_affiliation_id?: string;
  peer_affiliation_id?: string;
};

export type C19CreateGroupInput = {
  title: string;
  actor_affiliation_id?: string;
  members: C19ParticipantInput[];
};

export type C19UpdateGroupInput = {
  title: string;
};

export type C19AddGroupMembersInput = {
  members: C19ParticipantInput[];
};

export type C19TransferGroupOwnerInput = {
  new_owner_user_id: number;
};

export type C19UpdateConversationSettingsInput = Partial<
  Pick<
    C19ConversationSettings,
    "is_pinned" | "is_muted" | "is_archived" | "notification_level"
  >
>;

export type C19MessageContentType = "text" | "emoji";
export type C19MessageStatus = "sent" | "delivered" | "read";

/**
 * A durable message returned by the external C19 record service through Barong.
 * User identifiers remain transport-compatible while the storage boundary uses
 * opaque string identifiers internally.
 */
export type C19MessageRecord = {
  record_id: string;
  client_message_id: string;
  conversation_id: string;
  sequence: number;
  sender_user_id: number | string;
  recipient_user_ids: Array<number | string>;
  content_type: C19MessageContentType;
  content: string;
  status: C19MessageStatus;
  created_at: string;
  persisted_at: string;
  sender_org_id: string | null;
  recipient_org_ids: string[];
  metadata: Record<string, string>;
};

export type C19MessageHistoryPage = {
  records: C19MessageRecord[];
  next_cursor: string | null;
  latest_sequence: number;
};

export type C19SendMessageInput = {
  client_message_id: string;
  content_type: C19MessageContentType;
  content: string;
};

export type C19ReceiptPosition = {
  conversation_id: string;
  user_id: number | string;
  delivered_through_sequence: number;
  read_through_sequence: number;
  updated_at: string;
};

export type C19UnreadPosition = {
  conversation_id: string;
  user_id: number | string;
  unread_count: number;
  first_unread_sequence: number | null;
  latest_sequence: number;
};

export type C19ResumePosition = {
  conversation_id: string;
  user_id: number | string;
  resume_cursor: string | null;
  delivered_through_sequence: number;
  read_through_sequence: number;
  latest_sequence: number;
};

export type C19MessageEvent = {
  event_id: string;
  user_id: number | string;
  conversation_id: string;
  record_id: string;
  record_sequence: number;
  event_sequence: number;
  created_at: string;
};

export type C19MessageEventPage = {
  events: C19MessageEvent[];
  next_cursor: string | null;
  latest_event_sequence: number;
};

export type C19MessageEventTail = {
  cursor: string;
  latest_event_sequence: number;
};
