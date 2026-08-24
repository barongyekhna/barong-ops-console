"use client";

import {
  Ban,
  Camera,
  Check,
  ChevronLeft,
  CircleOff,
  ContactRound,
  MessageSquareText,
  MoreHorizontal,
  Pin,
  Plus,
  RefreshCcw,
  Search,
  Settings2,
  UserPlus,
  UsersRound,
  VolumeX,
  X,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError } from "@/lib/api";

import {
  actOnC19FriendRequest,
  addC19GroupMembers,
  createC19Block,
  createC19DirectConversation,
  createC19FriendRequest,
  createC19Group,
  dissolveC19Group,
  getC19Conversation,
  getC19Profile,
  getC19UnreadPosition,
  leaveC19Group,
  listC19Blocks,
  listC19Conversations,
  listC19Directory,
  listC19FriendRequests,
  listC19Friends,
  listC19MessageHistory,
  removeC19Block,
  removeC19Friend,
  removeC19GroupMember,
  transferC19GroupOwner,
  updateC19ConversationSettings,
  updateC19Group,
  updateC19MyProfile,
} from "./api";
import { C19Avatar } from "./C19Avatar";
import { C19ChatPanel } from "./C19ChatPanel";
import { C19MomentsPanel } from "./C19MomentsPanel";
import { C19ProfileCard } from "./C19ProfileCard";
import {
  C19_UNREAD_CHANGED_EVENT,
  normalizeC19UnreadCount,
} from "./C19UnreadStatus";
import styles from "./C19Workspace.module.css";
import type {
  C19Block,
  C19Conversation,
  C19ConversationMember,
  C19ConversationSettings,
  C19ConversationSummary,
  C19Friend,
  C19FriendRequest,
  C19MessageContentType,
  C19Profile,
} from "./types";

const LOAD_LIMIT = 100;
const SESSION_HINT_LIMIT = 30;
const SESSION_HINT_CONCURRENCY = 4;
const SESSION_HINT_REFRESH_MS = 30_000;

type WorkspaceTab = "chats" | "contacts" | "moments";
type ContactsView = "list" | "requests" | "blocks";

type SessionPreview = {
  at: string;
  content: string;
  contentType: C19MessageContentType;
  senderUserId: number | string;
};

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403) return "该操作被当前会话或关系安全规则拒绝。";
    if (error.status === 404) return "目标成员或会话已经不存在。";
    if (error.status === 409) return error.message || "该操作与当前状态冲突。";
    if (error.status >= 500) return "通讯服务暂时不可用。";
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

function readableDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function sessionTimeLabel(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const stamp = date.getTime();
  if (stamp >= startOfToday) {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }
  if (stamp >= startOfToday - 86_400_000) return "昨天";
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日`;
  }
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}

function previewBody(preview: SessionPreview) {
  if (preview.contentType === "image") return "[图片]";
  if (preview.contentType === "file") return "[文件]";
  return preview.content;
}

function memberRoleLabel(member: C19ConversationMember) {
  if (member.role === "owner") return "群主";
  if (member.role === "admin") return "管理员";
  return "成员";
}

function EmptyState({ children }: { children: string }) {
  return (
    <div className={styles.empty} role="status">
      {children}
    </div>
  );
}

export function C19Workspace() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chats");
  const [contactsView, setContactsView] = useState<ContactsView>("list");
  const [directory, setDirectory] = useState<C19Profile[]>([]);
  const [directoryCount, setDirectoryCount] = useState(0);
  const [isDirectorySearching, setIsDirectorySearching] = useState(false);
  const [knownOrganizations, setKnownOrganizations] = useState<
    Record<string, string>
  >({});
  const [authenticatedProfile, setAuthenticatedProfile] =
    useState<C19Profile | null>(null);
  const [authenticatedProfileError, setAuthenticatedProfileError] = useState("");
  const [profileRefreshGeneration, setProfileRefreshGeneration] = useState(0);
  const [friendRequests, setFriendRequests] = useState<C19FriendRequest[]>([]);
  const [friends, setFriends] = useState<C19Friend[]>([]);
  const [blocks, setBlocks] = useState<C19Block[]>([]);
  const [conversations, setConversations] = useState<C19ConversationSummary[]>([]);
  const [unreadById, setUnreadById] = useState<Record<string, number>>({});
  const [previewById, setPreviewById] = useState<
    Record<string, SessionPreview | null>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [search, setSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState("all");
  const [sessionFilter, setSessionFilter] = useState("");
  const [profileCard, setProfileCard] = useState<C19Profile | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [conversationDetail, setConversationDetail] =
    useState<C19Conversation | null>(null);
  const [conversationSettings, setConversationSettings] =
    useState<C19ConversationSettings | null>(null);
  const [detailError, setDetailError] = useState("");
  const [showConversationInfo, setShowConversationInfo] = useState(false);
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitle, setGroupTitle] = useState("");
  const [groupUserIds, setGroupUserIds] = useState<Set<number>>(() => new Set());
  const [renameTitle, setRenameTitle] = useState("");
  const [inviteUserId, setInviteUserId] = useState("");

  const conversationsRef = useRef<C19ConversationSummary[]>([]);
  conversationsRef.current = conversations;
  const hintsGenerationRef = useRef(0);
  const activeConversationRequestRef = useRef("");

  const loadControlData = useCallback(async (background = false) => {
    if (!background) setIsLoading(true);
    setLoadError("");
    const results = await Promise.allSettled([
      background
        ? Promise.resolve(null)
        : listC19Directory({ limit: LOAD_LIMIT, offset: 0 }),
      listC19FriendRequests({ limit: LOAD_LIMIT, offset: 0 }),
      listC19Friends({ limit: LOAD_LIMIT, offset: 0 }),
      listC19Blocks({ limit: LOAD_LIMIT, offset: 0 }),
      listC19Conversations({ limit: LOAD_LIMIT, offset: 0 }),
    ]);

    const failures = results.filter(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    );
    const [directoryResult, requestResult, friendResult, blockResult, conversationResult] =
      results;

    if (directoryResult.status === "fulfilled" && directoryResult.value) {
      const directoryPage = directoryResult.value;
      setDirectory(directoryPage.items);
      setDirectoryCount(directoryPage.count);
      setKnownOrganizations((current) => {
        const next = { ...current };
        for (const profile of directoryPage.items) {
          for (const affiliation of profile.affiliations) {
            next[affiliation.org_id] = affiliation.org_name;
          }
        }
        return next;
      });
    }
    if (requestResult.status === "fulfilled") setFriendRequests(requestResult.value.items);
    if (friendResult.status === "fulfilled") setFriends(friendResult.value.items);
    if (blockResult.status === "fulfilled") setBlocks(blockResult.value.items);
    if (conversationResult.status === "fulfilled") {
      setConversations(conversationResult.value.items);
    }

    if (failures.length > 0) {
      setLoadError(
        failures.length === results.length
          ? errorMessage(failures[0].reason, "通讯数据加载失败。")
          : `${failures.length} 组数据暂未同步，其余内容仍可操作。`,
      );
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void loadControlData();
  }, [loadControlData]);

  useEffect(() => {
    if (!user) {
      setAuthenticatedProfile(null);
      setAuthenticatedProfileError("");
      return;
    }
    let active = true;
    setAuthenticatedProfileError("");
    void getC19Profile(user.id)
      .then((profile) => {
        if (!active) return;
        setAuthenticatedProfile(profile);
      })
      .catch((error) => {
        if (!active) return;
        setAuthenticatedProfile(null);
        setAuthenticatedProfileError(
          errorMessage(error, "当前用户的通讯名片读取失败。"),
        );
      });
    return () => {
      active = false;
    };
  }, [profileRefreshGeneration, user]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setIsDirectorySearching(true);
      void listC19Directory({
        affiliation_org_id: orgFilter === "all" ? undefined : orgFilter,
        limit: LOAD_LIMIT,
        offset: 0,
        search: search.trim() || undefined,
      })
        .then((page) => {
          if (controller.signal.aborted) return;
          setDirectory(page.items);
          setDirectoryCount(page.count);
          setKnownOrganizations((current) => {
            const next = { ...current };
            for (const profile of page.items) {
              for (const affiliation of profile.affiliations) {
                next[affiliation.org_id] = affiliation.org_name;
              }
            }
            return next;
          });
        })
        .catch((error) => {
          if (!controller.signal.aborted) {
            setLoadError(errorMessage(error, "通讯录搜索失败。"));
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setIsDirectorySearching(false);
        });
    }, 260);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [orgFilter, search]);

  const profileByUserId = useMemo(() => {
    const map = new Map<number, C19Profile>();
    for (const profile of directory) map.set(profile.user_id, profile);
    for (const friend of friends) {
      if (!map.has(friend.profile.user_id)) {
        map.set(friend.profile.user_id, friend.profile);
      }
    }
    for (const block of blocks) {
      if (!map.has(block.profile.user_id)) {
        map.set(block.profile.user_id, block.profile);
      }
    }
    if (authenticatedProfile) {
      map.set(authenticatedProfile.user_id, authenticatedProfile);
    }
    return map;
  }, [authenticatedProfile, blocks, directory, friends]);
  const selfProfile =
    authenticatedProfile ?? (user ? profileByUserId.get(user.id) ?? null : null);
  const chatProfiles = useMemo(
    () => [...profileByUserId.values()],
    [profileByUserId],
  );
  const blockedUserIds = useMemo(
    () => new Set(blocks.map((block) => block.profile.user_id)),
    [blocks],
  );
  const friendUserIds = useMemo(
    () => new Set(friends.map((friend) => friend.profile.user_id)),
    [friends],
  );
  const pendingRequestUserIds = useMemo(() => {
    const values = new Set<number>();
    for (const request of friendRequests) {
      if (request.status !== "pending") continue;
      values.add(
        request.requester.user_id === user?.id
          ? request.addressee.user_id
          : request.requester.user_id,
      );
    }
    return values;
  }, [friendRequests, user?.id]);
  const incomingPendingCount = useMemo(
    () =>
      friendRequests.filter(
        (request) =>
          request.status === "pending" &&
          request.addressee.user_id === user?.id,
      ).length,
    [friendRequests, user?.id],
  );
  const organizations = useMemo(() => {
    return Object.entries(knownOrganizations).sort((left, right) =>
      left[1].localeCompare(right[1], "zh-CN"),
    );
  }, [knownOrganizations]);
  const filteredDirectory = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const matches = directory.filter((profile) => {
      if (
        orgFilter !== "all" &&
        !profile.affiliations.some((affiliation) => affiliation.org_id === orgFilter)
      ) {
        return false;
      }
      if (!normalizedSearch) return true;
      const haystack = [
        profile.display_name,
        profile.bio ?? "",
        ...profile.affiliations.flatMap((affiliation) => [
          affiliation.org_name,
          affiliation.role,
        ]),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearch);
    });
    return matches.sort((left, right) =>
      left.display_name.localeCompare(right.display_name, "zh-CN"),
    );
  }, [directory, orgFilter, search]);

  const refreshSessionHints = useCallback(async (items: C19ConversationSummary[]) => {
    const generation = ++hintsGenerationRef.current;
    const queue = items.slice(0, SESSION_HINT_LIMIT);
    let cursor = 0;
    const worker = async () => {
      for (;;) {
        if (hintsGenerationRef.current !== generation) return;
        const target = queue[cursor];
        cursor += 1;
        if (!target) return;
        const conversationId = target.conversation_id;
        try {
          const [unread, history] = await Promise.all([
            getC19UnreadPosition(conversationId),
            listC19MessageHistory(conversationId, { limit: 1 }),
          ]);
          if (hintsGenerationRef.current !== generation) return;
          setUnreadById((current) => ({
            ...current,
            [conversationId]: normalizeC19UnreadCount(unread.unread_count),
          }));
          const record =
            history.records.length > 0
              ? history.records[history.records.length - 1]
              : null;
          setPreviewById((current) => ({
            ...current,
            [conversationId]: record
              ? {
                  at: record.persisted_at,
                  content: record.content,
                  contentType: record.content_type,
                  senderUserId: record.sender_user_id,
                }
              : null,
          }));
        } catch {
          // 未读与预览是装饰性信息，读取失败不阻塞会话列表。
        }
      }
    };
    await Promise.all(
      Array.from({ length: SESSION_HINT_CONCURRENCY }, () => worker()),
    );
  }, []);

  const conversationHintKey = useMemo(
    () =>
      conversations
        .map((conversation) => conversation.conversation_id)
        .join(","),
    [conversations],
  );

  useEffect(() => {
    if (!conversationHintKey) return;
    void refreshSessionHints(conversationsRef.current);
  }, [conversationHintKey, refreshSessionHints]);

  useEffect(() => {
    const refresh = () => {
      if (conversationsRef.current.length === 0) return;
      void refreshSessionHints(conversationsRef.current);
    };
    const interval = window.setInterval(refresh, SESSION_HINT_REFRESH_MS);
    window.addEventListener(C19_UNREAD_CHANGED_EVENT, refresh);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener(C19_UNREAD_CHANGED_EVENT, refresh);
    };
  }, [refreshSessionHints]);

  const sessionName = useCallback(
    (conversation: C19ConversationSummary) => {
      if (conversation.type === "group") {
        return conversation.title || "群聊";
      }
      return conversation.direct_peer?.display_name ?? conversation.title ?? "单聊";
    },
    [],
  );

  const orderedConversations = useMemo(() => {
    const timeOf = (conversation: C19ConversationSummary) => {
      const preview = previewById[conversation.conversation_id];
      const stamp = new Date(preview?.at ?? conversation.updated_at).getTime();
      return Number.isNaN(stamp) ? 0 : stamp;
    };
    const filter = sessionFilter.trim().toLowerCase();
    const items = conversations.filter((conversation) =>
      filter ? sessionName(conversation).toLowerCase().includes(filter) : true,
    );
    return items.sort((left, right) => {
      if (left.settings.is_pinned !== right.settings.is_pinned) {
        return left.settings.is_pinned ? -1 : 1;
      }
      return timeOf(right) - timeOf(left);
    });
  }, [conversations, previewById, sessionFilter, sessionName]);

  const totalUnread = useMemo(
    () =>
      conversations.reduce(
        (sum, conversation) =>
          sum + (unreadById[conversation.conversation_id] ?? 0),
        0,
      ),
    [conversations, unreadById],
  );

  const runAction = useCallback(
    async (key: string, success: string, action: () => Promise<unknown>) => {
      if (busyKey) return;
      setBusyKey(key);
      setActionError("");
      setNotice("");
      try {
        await action();
        await loadControlData(true);
        setNotice(success);
      } catch (error) {
        setActionError(errorMessage(error, "通讯操作未完成。"));
      } finally {
        setBusyKey("");
      }
    },
    [busyKey, loadControlData],
  );

  const updateMyAvatar = useCallback(
    async (avatarRef: string | null) => {
      if (busyKey) throw new Error("另一个通讯操作正在进行，请稍后重试。");
      setBusyKey("avatar");
      setActionError("");
      setNotice("");
      try {
        const updated = await updateC19MyProfile({ avatar_ref: avatarRef });
        const replaceProfile = (profile: C19Profile) =>
          profile.user_id === updated.user_id ? updated : profile;
        setAuthenticatedProfile(updated);
        setProfileCard((current) =>
          current?.user_id === updated.user_id ? updated : current,
        );
        setDirectory((current) => current.map(replaceProfile));
        setFriends((current) =>
          current.map((friend) => ({
            ...friend,
            profile: replaceProfile(friend.profile),
          })),
        );
        setBlocks((current) =>
          current.map((block) => ({
            ...block,
            profile: replaceProfile(block.profile),
          })),
        );
        setFriendRequests((current) =>
          current.map((request) => ({
            ...request,
            addressee:
              request.addressee.user_id === updated.user_id
                ? {
                    ...request.addressee,
                    avatar_ref: updated.avatar_ref,
                    display_name: updated.display_name,
                  }
                : request.addressee,
            requester:
              request.requester.user_id === updated.user_id
                ? {
                    ...request.requester,
                    avatar_ref: updated.avatar_ref,
                    display_name: updated.display_name,
                  }
                : request.requester,
          })),
        );
        setConversations((current) =>
          current.map((conversation) =>
            conversation.direct_peer?.user_id === updated.user_id
              ? {
                  ...conversation,
                  direct_peer: {
                    ...conversation.direct_peer,
                    avatar_ref: updated.avatar_ref,
                    display_name: updated.display_name,
                  },
                }
              : conversation,
          ),
        );
        setNotice(avatarRef ? "头像已更新。" : "已恢复默认头像。");
      } catch (error) {
        const message = errorMessage(error, "头像更新失败。");
        setActionError(message);
        throw new Error(message);
      } finally {
        setBusyKey("");
      }
    },
    [busyKey],
  );

  const openConversation = useCallback(
    async (conversationId: string) => {
      activeConversationRequestRef.current = conversationId;
      setSelectedConversationId(conversationId);
      setShowConversationInfo(false);
      setConversationDetail(null);
      setConversationSettings(null);
      setDetailError("");
      setUnreadById((current) => ({ ...current, [conversationId]: 0 }));
      try {
        const conversation = await getC19Conversation(conversationId);
        if (activeConversationRequestRef.current !== conversationId) return;
        setConversationDetail(conversation);
        setConversationSettings(conversation.settings);
        setRenameTitle(conversation.title ?? "");
      } catch (error) {
        if (activeConversationRequestRef.current !== conversationId) return;
        setDetailError(errorMessage(error, "会话读取失败。"));
      }
    },
    [],
  );

  const adoptConversation = useCallback(
    (conversation: C19Conversation) => {
      activeConversationRequestRef.current = conversation.conversation_id;
      setActiveTab("chats");
      setSelectedConversationId(conversation.conversation_id);
      setConversationDetail(conversation);
      setConversationSettings(conversation.settings);
      setRenameTitle(conversation.title ?? "");
      setDetailError("");
      setShowConversationInfo(false);
      setConversations((current) => {
        if (
          current.some(
            (item) => item.conversation_id === conversation.conversation_id,
          )
        ) {
          return current;
        }
        const actorMember = conversation.members.find(
          (member) => member.user_id === user?.id,
        );
        const peerMember =
          conversation.type === "direct"
            ? conversation.members.find((member) => member.user_id !== user?.id)
            : null;
        const peerProfile = peerMember
          ? profileByUserId.get(peerMember.user_id)
          : null;
        const optimistic: C19ConversationSummary = {
          active_member_count: conversation.members.filter(
            (member) => member.status === "active",
          ).length,
          actor_org_id: actorMember?.org_id ?? null,
          actor_role: actorMember?.role ?? "member",
          conversation_id: conversation.conversation_id,
          created_at: conversation.created_at,
          direct_peer:
            peerMember && peerProfile
              ? {
                  avatar_ref: peerProfile.avatar_ref,
                  display_name: peerProfile.display_name,
                  user_id: peerProfile.user_id,
                }
              : null,
          settings: conversation.settings,
          status: conversation.status,
          title: conversation.title,
          type: conversation.type,
          updated_at: conversation.updated_at,
        };
        return [optimistic, ...current];
      });
    },
    [profileByUserId, user?.id],
  );

  const startChatWith = useCallback(
    async (profile: C19Profile) => {
      if (busyKey) return;
      setBusyKey(`direct:${profile.user_id}`);
      setActionError("");
      setNotice("");
      try {
        const conversation = await createC19DirectConversation({
          peer_user_id: profile.user_id,
        });
        setProfileCard(null);
        adoptConversation(conversation);
        void loadControlData(true);
      } catch (error) {
        setActionError(errorMessage(error, "会话建立失败。"));
      } finally {
        setBusyKey("");
      }
    },
    [adoptConversation, busyKey, loadControlData],
  );

  const openProfileCard = useCallback(
    async (userId: number) => {
      const existing = profileByUserId.get(userId);
      if (existing) {
        setProfileCard(existing);
        return;
      }
      try {
        setProfileCard(await getC19Profile(userId));
      } catch (error) {
        setActionError(errorMessage(error, "名片读取失败。"));
      }
    },
    [profileByUserId],
  );

  const submitGroup = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (busyKey) return;
      const selectedProfiles = [...groupUserIds].flatMap((userId) => {
        const profile = profileByUserId.get(userId);
        return profile ? [profile] : [];
      });
      if (selectedProfiles.length !== groupUserIds.size) {
        setActionError("部分群成员已不在通讯录中，请刷新后重新选择。");
        return;
      }
      if (selectedProfiles.length < 2) {
        setActionError("发起群聊至少还需要选择两位成员。");
        return;
      }
      const names = [
        ...(selfProfile ? [selfProfile.display_name] : []),
        ...selectedProfiles.map((profile) => profile.display_name),
      ];
      const autoTitle = `${names.slice(0, 3).join("、")}${
        names.length > 3 ? "等" : ""
      }的群聊`;
      const title = (groupTitle.trim() || autoTitle).slice(0, 255);
      setBusyKey("create-group");
      setActionError("");
      setNotice("");
      void (async () => {
        try {
          const conversation = await createC19Group({
            members: selectedProfiles.map((profile) => ({
              user_id: profile.user_id,
            })),
            title,
          });
          setGroupComposerOpen(false);
          setGroupTitle("");
          setGroupUserIds(new Set());
          adoptConversation(conversation);
          void loadControlData(true);
          setNotice("群聊已创建。");
        } catch (error) {
          setActionError(errorMessage(error, "群聊创建失败。"));
        } finally {
          setBusyKey("");
        }
      })();
    },
    [
      adoptConversation,
      busyKey,
      groupTitle,
      groupUserIds,
      loadControlData,
      profileByUserId,
      selfProfile,
    ],
  );

  const updateSettings = useCallback(
    (patch: Partial<C19ConversationSettings>) => {
      if (!conversationSettings || !selectedConversationId) return;
      void runAction("settings", "会话设置已保存。", async () => {
        const updated = await updateC19ConversationSettings(
          selectedConversationId,
          patch,
        );
        setConversationSettings(updated);
      });
    },
    [conversationSettings, runAction, selectedConversationId],
  );

  const selectedMember = useMemo(
    () =>
      conversationDetail?.members.find(
        (member) => member.user_id === user?.id && member.status === "active",
      ) ?? null,
    [conversationDetail?.members, user?.id],
  );
  const canManageGroup =
    selectedMember?.role === "owner" || selectedMember?.role === "admin";
  const canDissolveGroup = selectedMember?.role === "owner";

  const selectedSummary = useMemo(
    () =>
      conversations.find(
        (conversation) =>
          conversation.conversation_id === selectedConversationId,
      ) ?? null,
    [conversations, selectedConversationId],
  );
  const stagePeerUserId = useMemo(() => {
    if (!conversationDetail || conversationDetail.type !== "direct") return null;
    const peer = conversationDetail.members.find(
      (member) => member.user_id !== user?.id,
    );
    return peer?.user_id ?? null;
  }, [conversationDetail, user?.id]);
  const stageTitle = useMemo(() => {
    if (!conversationDetail) return "";
    if (conversationDetail.type === "group") {
      const activeCount = conversationDetail.members.filter(
        (member) => member.status === "active",
      ).length;
      return `${conversationDetail.title || "群聊"}（${activeCount}）`;
    }
    if (selectedSummary?.direct_peer?.display_name) {
      return selectedSummary.direct_peer.display_name;
    }
    const peerProfile =
      stagePeerUserId !== null ? profileByUserId.get(stagePeerUserId) : null;
    return peerProfile?.display_name ?? "单聊";
  }, [conversationDetail, profileByUserId, selectedSummary, stagePeerUserId]);

  const cardUser = profileCard;
  const cardIsSelf = cardUser?.user_id === user?.id;

  return (
    <section
      aria-busy={isLoading || isDirectorySearching}
      aria-label="通讯"
      className={styles.workspace}
    >
      {loadError ? <div className={styles.warning} role="alert">{loadError}</div> : null}
      {authenticatedProfileError ? (
        <div className={styles.warning} role="alert">
          <span>{authenticatedProfileError}</span>
          <button
            onClick={() => setProfileRefreshGeneration((current) => current + 1)}
            type="button"
          >
            重试通讯名片同步
          </button>
        </div>
      ) : null}
      {actionError ? <div className={styles.error} role="alert">{actionError}</div> : null}
      {notice ? <div className={styles.success} role="status">{notice}</div> : null}
      {!selfProfile && !isLoading ? (
        <div className={styles.warning} role="alert">
          正在同步当前用户的基础通讯名片，请稍后刷新重试。
        </div>
      ) : null}

      <div className={styles.appShell}>
        <nav aria-label="通讯功能区" className={styles.sideRail}>
          {(
            [
              ["chats", "聊天", MessageSquareText, totalUnread],
              ["contacts", "通讯录", ContactRound, incomingPendingCount],
              ["moments", "朋友圈", Camera, 0],
            ] as const
          ).map(([key, label, Icon, badge]) => (
            <button
              aria-current={activeTab === key ? "page" : undefined}
              className={activeTab === key ? styles.railButtonActive : styles.railButton}
              key={key}
              onClick={() => setActiveTab(key)}
              type="button"
            >
              <span className={styles.railIconWrap}>
                <Icon aria-hidden="true" size={21} />
                {badge > 0 ? (
                  <em className={styles.railBadge}>{badge > 99 ? "99+" : badge}</em>
                ) : null}
              </span>
              <small>{label}</small>
            </button>
          ))}
          {selfProfile ? (
            <button
              aria-label="查看我的名片并更换头像"
              className={styles.railProfile}
              onClick={() => setProfileCard(selfProfile)}
              title="我的头像"
              type="button"
            >
              <C19Avatar
                avatarRef={selfProfile.avatar_ref}
                className={styles.railProfileAvatar}
                name={selfProfile.display_name}
              />
              <small>我的头像</small>
            </button>
          ) : null}
          <button
            className={styles.railRefresh}
            disabled={isLoading}
            onClick={() => void loadControlData()}
            title="刷新"
            type="button"
          >
            <RefreshCcw aria-hidden="true" size={17} />
            <small>{isLoading ? "同步中" : "刷新"}</small>
          </button>
        </nav>

        <div className={styles.appBody}>
          {activeTab === "chats" ? (
            <div className={styles.chatsLayout}>
              <aside className={styles.sessionRail}>
                <div className={styles.sessionRailHead}>
                  <label className={styles.sessionSearch}>
                    <Search aria-hidden="true" size={14} />
                    <input
                      aria-label="搜索会话"
                      onChange={(event) => setSessionFilter(event.target.value)}
                      placeholder="搜索"
                      type="search"
                      value={sessionFilter}
                    />
                  </label>
                  <button
                    aria-label="发起群聊"
                    className={styles.newGroupButton}
                    onClick={() => setGroupComposerOpen(true)}
                    title="发起群聊"
                    type="button"
                  >
                    <Plus aria-hidden="true" size={17} />
                  </button>
                </div>
                <div className={styles.sessionList}>
                  {isLoading && conversations.length === 0 ? (
                    <div className={styles.loading} role="status">
                      正在读取会话…
                    </div>
                  ) : orderedConversations.length === 0 ? (
                    <EmptyState>
                      还没有会话。到通讯录里点一个人，就能直接开聊。
                    </EmptyState>
                  ) : (
                    orderedConversations.map((conversation) => {
                      const conversationId = conversation.conversation_id;
                      const name = sessionName(conversation);
                      const preview = previewById[conversationId];
                      const unread = unreadById[conversationId] ?? 0;
                      const previewText = preview
                        ? conversation.type === "group" &&
                          String(preview.senderUserId) !== String(user?.id)
                          ? `${
                              profileByUserId.get(Number(preview.senderUserId))
                                ?.display_name ?? "成员"
                            }：${previewBody(preview)}`
                          : previewBody(preview)
                        : "";
                      return (
                        <button
                          className={
                            selectedConversationId === conversationId
                              ? styles.sessionRowActive
                              : styles.sessionRow
                          }
                          key={conversationId}
                          onClick={() => void openConversation(conversationId)}
                          type="button"
                        >
                          {conversation.type === "group" ? (
                            <span
                              aria-hidden="true"
                              className={styles.sessionGroupAvatar}
                            >
                              <UsersRound aria-hidden="true" size={19} />
                            </span>
                          ) : (
                            <C19Avatar
                              avatarRef={conversation.direct_peer?.avatar_ref}
                              className={styles.sessionAvatar}
                              name={name}
                            />
                          )}
                          <span className={styles.sessionMeta}>
                            <span className={styles.sessionTopLine}>
                              <strong>{name}</strong>
                              <time>
                                {sessionTimeLabel(
                                  preview?.at ?? conversation.updated_at,
                                )}
                              </time>
                            </span>
                            <span className={styles.sessionBottomLine}>
                              <small>{previewText}</small>
                              <span className={styles.sessionFlags}>
                                {conversation.settings.is_pinned ? (
                                  <Pin aria-hidden="true" size={12} />
                                ) : null}
                                {conversation.settings.is_muted ? (
                                  <VolumeX aria-hidden="true" size={12} />
                                ) : null}
                                {unread > 0 ? (
                                  <em
                                    className={
                                      conversation.settings.is_muted
                                        ? styles.unreadBadgeMuted
                                        : styles.unreadBadge
                                    }
                                  >
                                    {unread > 99 ? "99+" : unread}
                                  </em>
                                ) : null}
                              </span>
                            </span>
                          </span>
                        </button>
                      );
                    })
                  )}
                </div>
              </aside>

              <section className={styles.chatStage}>
                {!selectedConversationId ? (
                  <div className={styles.chatStageEmpty}>
                    <MessageSquareText aria-hidden="true" size={42} />
                    <p>选择左侧会话，或到通讯录点一个人直接开聊。</p>
                  </div>
                ) : detailError ? (
                  <div className={styles.error} role="alert">
                    <span>{detailError}</span>
                    <button
                      onClick={() => void openConversation(selectedConversationId)}
                      type="button"
                    >
                      重试读取会话
                    </button>
                  </div>
                ) : !conversationDetail || !conversationSettings ? (
                  <div className={styles.loading} role="status">
                    正在读取会话…
                  </div>
                ) : user ? (
                  <>
                    <C19ChatPanel
                      conversation={conversationDetail}
                      headerActions={
                        <button
                          aria-expanded={showConversationInfo}
                          aria-label="会话信息与设置"
                          className={styles.stageMenuButton}
                          onClick={() =>
                            setShowConversationInfo((current) => !current)
                          }
                          type="button"
                        >
                          <MoreHorizontal aria-hidden="true" size={19} />
                        </button>
                      }
                      profiles={chatProfiles}
                      title={stageTitle}
                      userId={user.id}
                    />
                    {showConversationInfo ? (
                      <ConversationInfoDrawer
                        busy={Boolean(busyKey)}
                        canDissolveGroup={canDissolveGroup}
                        canManageGroup={canManageGroup}
                        conversation={conversationDetail}
                        directory={directory}
                        inviteUserId={inviteUserId}
                        onAddMember={() => {
                          const profile = profileByUserId.get(Number(inviteUserId));
                          if (!profile) {
                            setActionError(
                              "该用户已不在通讯录中，请刷新后重新选择。",
                            );
                            return;
                          }
                          void runAction(
                            "add-member",
                            "成员已加入群聊。",
                            async () => {
                              const updated = await addC19GroupMembers(
                                conversationDetail.conversation_id,
                                { members: [{ user_id: profile.user_id }] },
                              );
                              setConversationDetail(updated);
                              setInviteUserId("");
                            },
                          );
                        }}
                        onClose={() => setShowConversationInfo(false)}
                        onDissolve={() => {
                          if (!window.confirm("确定解散这个群聊吗？")) return;
                          void runAction("dissolve", "群聊已解散。", async () => {
                            await dissolveC19Group(
                              conversationDetail.conversation_id,
                            );
                            setSelectedConversationId("");
                            setConversationDetail(null);
                            setShowConversationInfo(false);
                          });
                        }}
                        onInviteUserChange={setInviteUserId}
                        onLeave={() => {
                          if (!window.confirm("确定退出这个群聊吗？")) return;
                          void runAction("leave", "你已退出群聊。", async () => {
                            await leaveC19Group(conversationDetail.conversation_id);
                            setSelectedConversationId("");
                            setConversationDetail(null);
                            setShowConversationInfo(false);
                          });
                        }}
                        onOpenProfile={(userId) => void openProfileCard(userId)}
                        onRemoveMember={(member) =>
                          void runAction(
                            `remove-member:${member.user_id}`,
                            "成员已移出群聊。",
                            async () => {
                              const updated = await removeC19GroupMember(
                                conversationDetail.conversation_id,
                                member.user_id,
                              );
                              setConversationDetail(updated);
                            },
                          )
                        }
                        onRename={(event) => {
                          event.preventDefault();
                          if (!renameTitle.trim()) return;
                          void runAction("rename", "群名已更新。", async () => {
                            const updated = await updateC19Group(
                              conversationDetail.conversation_id,
                              { title: renameTitle.trim() },
                            );
                            setConversationDetail(updated);
                          });
                        }}
                        onRenameTitleChange={setRenameTitle}
                        onSettingsChange={updateSettings}
                        onTransferOwner={(member) => {
                          if (!window.confirm("确定把群主转让给这位成员吗？")) return;
                          void runAction("transfer-owner", "群主已转让。", async () => {
                            const updated = await transferC19GroupOwner(
                              conversationDetail.conversation_id,
                              { new_owner_user_id: member.user_id },
                            );
                            setConversationDetail(updated);
                          });
                        }}
                        peerUserId={stagePeerUserId}
                        profileByUserId={profileByUserId}
                        renameTitle={renameTitle}
                        selfUserId={user.id}
                        settings={conversationSettings}
                      />
                    ) : null}
                  </>
                ) : null}
              </section>
            </div>
          ) : null}

          {activeTab === "contacts" ? (
            <div className={styles.contactsLayout}>
              {contactsView === "list" ? (
                <>
                  <div className={styles.contactsHead}>
                    <label className={styles.sessionSearch}>
                      <Search aria-hidden="true" size={14} />
                      <input
                        aria-label="搜索通讯录"
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="搜索成员"
                        type="search"
                        value={search}
                      />
                    </label>
                    {isDirectorySearching ? (
                      <span className={styles.searching}>同步中</span>
                    ) : (
                      <span className={styles.contactsCount}>
                        {directoryCount} 位成员
                      </span>
                    )}
                  </div>

                  <div aria-label="按组织筛选" className={styles.orgFilters}>
                    <button
                      className={orgFilter === "all" ? styles.selectedFilter : ""}
                      onClick={() => setOrgFilter("all")}
                      type="button"
                    >
                      全部成员
                    </button>
                    {organizations.map(([orgId, orgName]) => (
                      <button
                        className={orgFilter === orgId ? styles.selectedFilter : ""}
                        key={orgId}
                        onClick={() => setOrgFilter(orgId)}
                        type="button"
                      >
                        {orgName}
                      </button>
                    ))}
                  </div>

                  <div className={styles.contactEntries}>
                    <button
                      className={styles.contactEntryRow}
                      onClick={() => setContactsView("requests")}
                      type="button"
                    >
                      <span aria-hidden="true" className={styles.entryIconNew}>
                        <UserPlus aria-hidden="true" size={17} />
                      </span>
                      新的朋友
                      {incomingPendingCount > 0 ? (
                        <em className={styles.entryBadge}>{incomingPendingCount}</em>
                      ) : null}
                    </button>
                    <button
                      className={styles.contactEntryRow}
                      onClick={() => setContactsView("blocks")}
                      type="button"
                    >
                      <span aria-hidden="true" className={styles.entryIconBlock}>
                        <Ban aria-hidden="true" size={16} />
                      </span>
                      黑名单
                      {blocks.length > 0 ? (
                        <em className={styles.entryBadgePlain}>{blocks.length}</em>
                      ) : null}
                    </button>
                  </div>

                  <div className={styles.contactList}>
                    {filteredDirectory.length === 0 ? (
                      <EmptyState>没有匹配的成员。</EmptyState>
                    ) : (
                      filteredDirectory.map((profile) => {
                        const isSelf = profile.user_id === user?.id;
                        return (
                          <button
                            className={styles.contactRowBtn}
                            key={profile.user_id}
                            onClick={() => setProfileCard(profile)}
                            type="button"
                          >
                            <C19Avatar
                              avatarRef={profile.avatar_ref}
                              className={styles.contactAvatar}
                              name={profile.display_name}
                            />
                            <span className={styles.contactRowMeta}>
                              <strong>
                                {profile.display_name}
                                {isSelf ? (
                                  <em className={styles.profileSelfTag}>本人</em>
                                ) : null}
                                {friendUserIds.has(profile.user_id) && !isSelf ? (
                                  <em className={styles.profileFriendTag}>好友</em>
                                ) : null}
                              </strong>
                              <small>
                                {profile.affiliations.length > 0
                                  ? profile.affiliations
                                      .map((affiliation) => affiliation.org_name)
                                      .join(" · ")
                                  : profile.bio || "暂未加入组织"}
                              </small>
                            </span>
                          </button>
                        );
                      })
                    )}
                  </div>
                </>
              ) : null}

              {contactsView === "requests" ? (
                <div className={styles.contactsSubview}>
                  <div className={styles.subviewHead}>
                    <button
                      aria-label="返回通讯录"
                      className={styles.backBtn}
                      onClick={() => setContactsView("list")}
                      type="button"
                    >
                      <ChevronLeft aria-hidden="true" size={17} />
                    </button>
                    <h3>新的朋友</h3>
                    <span className={styles.countBadge}>{friendRequests.length}</span>
                  </div>
                  {friendRequests.length === 0 ? (
                    <EmptyState>暂无好友申请。</EmptyState>
                  ) : (
                    <div className={styles.stack}>
                      {friendRequests.map((request) => {
                        const incoming = request.addressee.user_id === user?.id;
                        const summary = incoming
                          ? request.requester
                          : request.addressee;
                        return (
                          <article className={styles.rowCard} key={request.request_id}>
                            <div>
                              <strong>{summary.display_name}</strong>
                              <span>
                                {incoming ? "向你发起申请" : "你发出的申请"} ·{" "}
                                {request.status === "pending" ? "待处理" : request.status === "accepted" ? "已通过" : request.status === "rejected" ? "已拒绝" : "已取消"}
                              </span>
                              {request.request_message ? (
                                <p>{request.request_message}</p>
                              ) : null}
                            </div>
                            {request.status === "pending" ? (
                              <div className={styles.inlineActions}>
                                {incoming ? (
                                  <>
                                    <button
                                      disabled={Boolean(busyKey)}
                                      onClick={() =>
                                        void runAction(
                                          `accept:${request.request_id}`,
                                          "好友申请已接受。",
                                          () =>
                                            actOnC19FriendRequest(
                                              request.request_id,
                                              "accept",
                                            ),
                                        )
                                      }
                                      type="button"
                                    >
                                      <Check aria-hidden="true" size={15} />接受
                                    </button>
                                    <button
                                      disabled={Boolean(busyKey)}
                                      onClick={() =>
                                        void runAction(
                                          `reject:${request.request_id}`,
                                          "好友申请已拒绝。",
                                          () =>
                                            actOnC19FriendRequest(
                                              request.request_id,
                                              "reject",
                                            ),
                                        )
                                      }
                                      type="button"
                                    >
                                      <X aria-hidden="true" size={15} />拒绝
                                    </button>
                                  </>
                                ) : (
                                  <button
                                    disabled={Boolean(busyKey)}
                                    onClick={() =>
                                      void runAction(
                                        `cancel:${request.request_id}`,
                                        "好友申请已取消。",
                                        () =>
                                          actOnC19FriendRequest(
                                            request.request_id,
                                            "cancel",
                                          ),
                                      )
                                    }
                                    type="button"
                                  >
                                    <CircleOff aria-hidden="true" size={15} />取消
                                  </button>
                                )}
                              </div>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : null}

              {contactsView === "blocks" ? (
                <div className={styles.contactsSubview}>
                  <div className={styles.subviewHead}>
                    <button
                      aria-label="返回通讯录"
                      className={styles.backBtn}
                      onClick={() => setContactsView("list")}
                      type="button"
                    >
                      <ChevronLeft aria-hidden="true" size={17} />
                    </button>
                    <h3>黑名单</h3>
                    <span className={styles.countBadge}>{blocks.length}</span>
                  </div>
                  {blocks.length === 0 ? (
                    <EmptyState>黑名单为空。</EmptyState>
                  ) : (
                    <div className={styles.stack}>
                      {blocks.map((block) => (
                        <article className={styles.rowCard} key={block.block_id}>
                          <div>
                            <strong>{block.profile.display_name}</strong>
                            <span>拉黑于 {readableDate(block.blocked_at)}</span>
                          </div>
                          <button
                            disabled={Boolean(busyKey)}
                            onClick={() =>
                              void runAction(
                                `unblock:${block.profile.user_id}`,
                                "已解除拉黑。",
                                () => removeC19Block(block.profile.user_id),
                              )
                            }
                            type="button"
                          >
                            解除拉黑
                          </button>
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}

          {activeTab === "moments" ? (
            selfProfile && user ? (
              <div className={styles.momentsHost}>
                <C19MomentsPanel profile={selfProfile} userId={user.id} />
              </div>
            ) : (
              <EmptyState>正在同步你的基础通讯名片，完成后即可读取朋友圈。</EmptyState>
            )
          ) : null}
        </div>
      </div>

      {cardUser ? (
        <C19ProfileCard
          busy={Boolean(busyKey)}
          isBlocked={blockedUserIds.has(cardUser.user_id)}
          isFriend={friendUserIds.has(cardUser.user_id)}
          isPending={pendingRequestUserIds.has(cardUser.user_id)}
          isSelf={Boolean(cardIsSelf)}
          onBlock={(profile) => {
            if (!window.confirm(`确定拉黑 ${profile.display_name} 吗？`)) return;
            void runAction(
              `block:${profile.user_id}`,
              `已将 ${profile.display_name} 加入黑名单。`,
              () => createC19Block(profile.user_id),
            );
          }}
          onClose={() => setProfileCard(null)}
          onRemoveFriend={(profile) => {
            if (!window.confirm(`确定解除与 ${profile.display_name} 的好友关系吗？`)) {
              return;
            }
            void runAction(
              `remove-friend:${profile.user_id}`,
              "好友关系已解除。",
              () => removeC19Friend(profile.user_id),
            );
          }}
          onSendFriendRequest={(profile, message) =>
            void runAction(
              `friend:${profile.user_id}`,
              `已向 ${profile.display_name} 提交好友申请。`,
              () =>
                createC19FriendRequest({
                  addressee_user_id: profile.user_id,
                  request_message: message || undefined,
                }),
            )
          }
          onStartChat={(profile) => void startChatWith(profile)}
          onUnblock={(profile) =>
            void runAction(
              `unblock:${profile.user_id}`,
              "已解除拉黑。",
              () => removeC19Block(profile.user_id),
            )
          }
          onUpdateAvatar={updateMyAvatar}
          profile={cardUser}
        />
      ) : null}

      {groupComposerOpen ? (
        <div
          aria-modal="true"
          className={styles.profileMask}
          onClick={(event) => {
            if (event.target === event.currentTarget) setGroupComposerOpen(false);
          }}
          role="dialog"
        >
          <form
            aria-label="发起群聊"
            className={styles.groupComposerCard}
            onSubmit={submitGroup}
          >
            <div className={styles.subviewHead}>
              <h3>
                <UsersRound aria-hidden="true" size={18} />
                发起群聊
              </h3>
              <button
                aria-label="关闭"
                className={styles.backBtn}
                onClick={() => setGroupComposerOpen(false)}
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
            <label className={styles.field}>
              <span>群聊名称（可留空，自动按成员命名）</span>
              <input
                maxLength={255}
                onChange={(event) => setGroupTitle(event.target.value)}
                placeholder="例如：跨组织选品协作"
                value={groupTitle}
              />
            </label>
            <div className={styles.groupMemberList}>
              {directory
                .filter((profile) => profile.user_id !== user?.id)
                .map((profile) => {
                  const selected = groupUserIds.has(profile.user_id);
                  return (
                    <label
                      className={
                        selected ? styles.memberCheckRowActive : styles.memberCheckRow
                      }
                      key={profile.user_id}
                    >
                      <input
                        checked={selected}
                        onChange={(event) =>
                          setGroupUserIds((current) => {
                            const next = new Set(current);
                            if (event.target.checked) next.add(profile.user_id);
                            else next.delete(profile.user_id);
                            return next;
                          })
                        }
                        type="checkbox"
                      />
                      <C19Avatar
                        avatarRef={profile.avatar_ref}
                        className={styles.contactAvatar}
                        name={profile.display_name}
                      />
                      <span>{profile.display_name}</span>
                    </label>
                  );
                })}
            </div>
            <button
              className={styles.primaryButton}
              disabled={Boolean(busyKey) || groupUserIds.size < 2}
              type="submit"
            >
              <UsersRound aria-hidden="true" size={16} />
              {groupUserIds.size < 2
                ? "至少再选择两位成员"
                : `创建群聊（${groupUserIds.size + 1} 人）`}
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}

function ConversationInfoDrawer({
  busy,
  canDissolveGroup,
  canManageGroup,
  conversation,
  directory,
  inviteUserId,
  onAddMember,
  onClose,
  onDissolve,
  onInviteUserChange,
  onLeave,
  onOpenProfile,
  onRemoveMember,
  onRename,
  onRenameTitleChange,
  onSettingsChange,
  onTransferOwner,
  peerUserId,
  profileByUserId,
  renameTitle,
  selfUserId,
  settings,
}: {
  busy: boolean;
  canDissolveGroup: boolean;
  canManageGroup: boolean;
  conversation: C19Conversation;
  directory: C19Profile[];
  inviteUserId: string;
  onAddMember: () => void;
  onClose: () => void;
  onDissolve: () => void;
  onInviteUserChange: (userId: string) => void;
  onLeave: () => void;
  onOpenProfile: (userId: number) => void;
  onRemoveMember: (member: C19ConversationMember) => void;
  onRename: (event: FormEvent<HTMLFormElement>) => void;
  onRenameTitleChange: (title: string) => void;
  onSettingsChange: (patch: Partial<C19ConversationSettings>) => void;
  onTransferOwner: (member: C19ConversationMember) => void;
  peerUserId: number | null;
  profileByUserId: Map<number, C19Profile>;
  renameTitle: string;
  selfUserId: number;
  settings: C19ConversationSettings;
}) {
  const isGroup = conversation.type === "group";
  const activeMembers = conversation.members.filter(
    (member) => member.status === "active",
  );
  const memberIds = new Set(conversation.members.map((member) => member.user_id));
  const availableProfiles = directory.filter(
    (profile) => !memberIds.has(profile.user_id),
  );

  return (
    <aside aria-label="会话信息与设置" className={styles.infoDrawer}>
      <div className={styles.subviewHead}>
        <h3>{isGroup ? "群聊信息" : "会话信息"}</h3>
        <button
          aria-label="关闭会话信息"
          className={styles.backBtn}
          onClick={onClose}
          type="button"
        >
          <X aria-hidden="true" size={16} />
        </button>
      </div>

      {!isGroup && peerUserId !== null ? (
        <button
          className={styles.drawerPeerCard}
          onClick={() => onOpenProfile(peerUserId)}
          type="button"
        >
          <C19Avatar
            avatarRef={profileByUserId.get(peerUserId)?.avatar_ref}
            className={styles.contactAvatar}
            name={profileByUserId.get(peerUserId)?.display_name ?? "成员"}
          />
          <span>
            <strong>
              {profileByUserId.get(peerUserId)?.display_name ??
                "未命名成员"}
            </strong>
            <small>查看名片</small>
          </span>
        </button>
      ) : null}

      <section className={styles.settingsSection}>
        <h4>
          <Settings2 aria-hidden="true" size={16} />
          我的会话设置
        </h4>
        <div className={styles.settingGrid}>
          <label>
            <input
              checked={settings.is_pinned}
              onChange={(event) =>
                onSettingsChange({ is_pinned: event.target.checked })
              }
              type="checkbox"
            />
            <Pin aria-hidden="true" size={15} />
            置顶
          </label>
          <label>
            <input
              checked={settings.is_muted}
              onChange={(event) =>
                onSettingsChange({ is_muted: event.target.checked })
              }
              type="checkbox"
            />
            <VolumeX aria-hidden="true" size={15} />
            静音
          </label>
          <label>
            <input
              checked={settings.is_archived}
              onChange={(event) =>
                onSettingsChange({ is_archived: event.target.checked })
              }
              type="checkbox"
            />
            归档
          </label>
          <label>
            <span>通知级别</span>
            <select
              onChange={(event) =>
                onSettingsChange({
                  notification_level: event.target.value as
                    | "all"
                    | "mentions"
                    | "none",
                })
              }
              value={settings.notification_level}
            >
              <option value="all">全部</option>
              <option value="mentions">仅提及</option>
              <option value="none">不通知</option>
            </select>
          </label>
        </div>
      </section>

      {isGroup ? (
        <section className={styles.membersSection}>
          <div className={styles.sectionHeading}>
            <h4>
              <UsersRound aria-hidden="true" size={16} />
              成员
            </h4>
            <span>{activeMembers.length}</span>
          </div>
          <div className={styles.stack}>
            {activeMembers.map((member) => {
              const profile = profileByUserId.get(member.user_id);
              return (
                <article
                  className={styles.memberRow}
                  key={`${conversation.conversation_id}:${member.user_id}`}
                >
                  <button
                    className={styles.memberNameBtn}
                    onClick={() => onOpenProfile(member.user_id)}
                    type="button"
                  >
                    <C19Avatar
                      avatarRef={profile?.avatar_ref}
                      className={styles.contactAvatar}
                      name={profile?.display_name ?? "成员"}
                    />
                    <span>
                      <strong>
                        {profile?.display_name ?? "未命名成员"}
                        {member.user_id === selfUserId ? (
                          <em className={styles.profileSelfTag}>我</em>
                        ) : null}
                      </strong>
                      <small>{memberRoleLabel(member)}</small>
                    </span>
                  </button>
                  {member.user_id !== selfUserId ? (
                    <div className={styles.inlineActions}>
                      {canDissolveGroup ? (
                        <button
                          disabled={busy}
                          onClick={() => onTransferOwner(member)}
                          type="button"
                        >
                          转让群主
                        </button>
                      ) : null}
                      {canManageGroup ? (
                        <button
                          className={styles.dangerButton}
                          disabled={busy}
                          onClick={() => onRemoveMember(member)}
                          type="button"
                        >
                          移除
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {isGroup ? (
        <section className={styles.groupControls}>
          {canManageGroup ? (
            <>
              <form onSubmit={onRename}>
                <label className={styles.field}>
                  <span>群聊名称</span>
                  <input
                    maxLength={255}
                    onChange={(event) => onRenameTitleChange(event.target.value)}
                    value={renameTitle}
                  />
                </label>
                <button disabled={busy} type="submit">
                  保存名称
                </button>
              </form>
              <div className={styles.inviteControl}>
                <label className={styles.field}>
                  <span>邀请成员</span>
                  <select
                    onChange={(event) => onInviteUserChange(event.target.value)}
                    value={inviteUserId}
                  >
                    <option value="">选择成员</option>
                    {availableProfiles.map((profile) => (
                      <option key={profile.user_id} value={profile.user_id}>
                        {profile.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  disabled={busy || !inviteUserId}
                  onClick={onAddMember}
                  type="button"
                >
                  邀请加入
                </button>
              </div>
            </>
          ) : null}
          <div className={styles.destructiveActions}>
            <button disabled={busy} onClick={onLeave} type="button">
              退出群聊
            </button>
            {canDissolveGroup ? (
              <button
                className={styles.dangerButton}
                disabled={busy}
                onClick={onDissolve}
                type="button"
              >
                解散群聊
              </button>
            ) : null}
          </div>
        </section>
      ) : null}
    </aside>
  );
}
