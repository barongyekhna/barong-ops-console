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
  affiliation_id: string | null;
  user_id: number;
  org_id: string | null;
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
  actor_org_id: string | null;
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
  affiliation_id?: string;
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

export type C19AssetKind = "image" | "file";
export type C19AssetStatus =
  | "pending_upload"
  | "uploaded"
  | "scanning"
  | "active"
  | "rejected"
  | "quarantined"
  | "delete_pending"
  | "deleted"
  | "expired";

export type C19Asset = {
  asset_id: string;
  client_asset_id: string;
  kind: C19AssetKind;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256_hex: string;
  version: number;
  status: C19AssetStatus;
};

export type C19AssetReference = Omit<C19Asset, "status"> & {
  ordinal: number;
};

export type C19AssetUploadIntentInput = {
  client_asset_id: string;
  kind: C19AssetKind;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256_hex: string;
};

export type C19AssetUploadIntent = {
  asset: C19Asset;
  upload_locator: string | null;
  expires_at: string | null;
};

export type C19AssetAccessVariant = "original" | "thumbnail";

export type C19AssetAccessIntent = {
  download_locator: string;
  expires_at: string;
};

export type C19MessageContentType = "text" | "emoji" | "image" | "file";
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
  assets: C19AssetReference[];
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
  asset?: {
    asset_id: string;
  };
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

export type C19UnreadSummary = {
  total_unread_count: number;
  unread_conversation_count: number;
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

export type C19MomentVisibility = "public" | "org" | "friends" | "private";

export type C19MomentAudienceOrganization = {
  org_id: string;
  org_name: string;
};

export type C19Moment = {
  moment_id: string;
  client_moment_id: string;
  author_org_id: string | null;
  author: C19ProfileSummary;
  content: string;
  visibility: C19MomentVisibility;
  audience_organizations: C19MomentAudienceOrganization[];
  state: "published";
  assets: C19AssetReference[];
  like_count: number;
  comment_count: number;
  viewer_has_liked: boolean;
  created_at: string;
  published_at: string;
};

export type C19MomentDraft = {
  moment_id: string;
  client_moment_id: string;
  state: "draft" | "published" | "delete_pending" | "deleted";
  created_at: string;
  persisted_at: string;
};

export type C19CreateMomentDraftInput = {
  client_moment_id: string;
};

export type C19PublishMomentInput = {
  content: string;
  visibility: C19MomentVisibility;
  audience_affiliation_ids?: string[];
  asset_ids: string[];
};

export type C19MomentFeedPage = {
  moments: C19Moment[];
  next_cursor: string | null;
  latest_event_sequence: number;
};

export type C19MomentDeleteResponse = {
  moment_id: string;
  state: "deleted";
};

export type C19MomentLike = {
  profile: C19ProfileSummary;
  sequence: number;
  created_at: string;
};

export type C19MomentLikePage = {
  likes: C19MomentLike[];
  next_cursor: string | null;
};

export type C19MomentLikeMutation = {
  moment_id: string;
  liked: boolean;
  changed: boolean;
  like_count: number;
  updated_at: string;
};

export type C19MomentComment = {
  comment_id: string;
  moment_id: string;
  client_comment_id: string;
  author: C19ProfileSummary;
  content: string;
  state: "active";
  sequence: number;
  created_at: string;
  persisted_at: string;
};

export type C19MomentCommentPage = {
  comments: C19MomentComment[];
  next_cursor: string | null;
};

export type C19CreateMomentCommentInput = {
  client_comment_id: string;
  content: string;
};

export type C19MomentCommentDeleteResponse = {
  moment_id: string;
  comment_id: string;
  state: "deleted";
  changed: boolean;
  comment_count: number;
  deleted_at: string;
};

export type C19MomentEventType =
  | "published"
  | "deleted"
  | "liked"
  | "unliked"
  | "commented"
  | "comment_deleted";

export type C19MomentEvent = {
  event_id: string;
  event_sequence: number;
  event_type: C19MomentEventType;
  moment_id: string;
  actor_user_id: number | string;
  comment_id: string | null;
  created_at: string;
};

export type C19MomentEventPage = {
  events: C19MomentEvent[];
  next_cursor: string | null;
  latest_event_sequence: number;
};

export type C19MomentEventTail = {
  cursor: string;
  latest_event_sequence: number;
};

export type C19MomentAssetUploadIntent = C19AssetUploadIntent & {
  moment_id: string;
};
