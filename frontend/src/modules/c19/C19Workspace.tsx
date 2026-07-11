"use client";

import {
  Ban,
  Check,
  CircleOff,
  ContactRound,
  MessageSquareLock,
  Pin,
  RefreshCcw,
  Search,
  Settings2,
  ShieldCheck,
  UserMinus,
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
  getC19ConversationSettings,
  getC19Profile,
  leaveC19Group,
  listC19Blocks,
  listC19Conversations,
  listC19Directory,
  listC19FriendRequests,
  listC19Friends,
  removeC19Block,
  removeC19Friend,
  removeC19GroupMember,
  transferC19GroupOwner,
  updateC19ConversationSettings,
  updateC19Group,
} from "./api";
import { C19ChatPanel } from "./C19ChatPanel";
import styles from "./C19Workspace.module.css";
import type {
  C19Affiliation,
  C19Block,
  C19Conversation,
  C19ConversationSummary,
  C19ConversationMember,
  C19ConversationSettings,
  C19Friend,
  C19FriendRequest,
  C19ParticipantInput,
  C19Profile,
} from "./types";

const LOAD_LIMIT = 100;
type WorkspaceTab = "contacts" | "relationships" | "conversations";

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403) return "当前身份无权执行此 C19 操作。";
    if (error.status === 404) return "目标成员或控制记录已经不存在。";
    if (error.status === 409) return error.message || "该操作与当前状态冲突。";
    if (error.status >= 500) return "C19 控制服务暂时不可用。";
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

function initials(name: string) {
  const normalized = name.trim();
  return normalized ? normalized.slice(0, 2).toUpperCase() : "成员";
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

function activeAffiliations(profile: C19Profile | null | undefined) {
  return profile?.affiliations ?? [];
}

function affiliationLabel(affiliation: C19Affiliation) {
  const role =
    affiliation.role === "owner"
      ? "Owner"
      : affiliation.role === "admin"
        ? "管理员"
        : "成员";
  return `${affiliation.org_name} · ${role}`;
}

function ProfileAvatar({ profile }: { profile: C19Profile }) {
  return (
    <span aria-hidden="true" className={styles.avatar}>
      {initials(profile.display_name)}
    </span>
  );
}

function IdentitySelect({
  compact = false,
  label,
  onChange,
  profile,
  value,
}: {
  compact?: boolean;
  label: string;
  onChange: (affiliationId: string) => void;
  profile: C19Profile;
  value: string;
}) {
  const affiliations = activeAffiliations(profile);
  const requiresChoice = affiliations.length > 1 && !value;

  return (
    <label className={compact ? styles.compactField : styles.field}>
      <span>{label}</span>
      <select
        aria-invalid={requiresChoice || undefined}
        disabled={affiliations.length === 0}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {affiliations.length !== 1 ? (
          <option value="">请选择组织身份</option>
        ) : null}
        {affiliations.map((affiliation) => (
          <option key={affiliation.affiliation_id} value={affiliation.affiliation_id}>
            {affiliationLabel(affiliation)}
          </option>
        ))}
      </select>
      {requiresChoice ? <small>多组织成员必须明确选择，系统不会猜测。</small> : null}
    </label>
  );
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
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("contacts");
  const [directory, setDirectory] = useState<C19Profile[]>([]);
  const [directoryCount, setDirectoryCount] = useState(0);
  const [isDirectorySearching, setIsDirectorySearching] = useState(false);
  const [knownOrganizations, setKnownOrganizations] = useState<
    Record<string, string>
  >({});
  const [authenticatedProfile, setAuthenticatedProfile] =
    useState<C19Profile | null>(null);
  const [authenticatedProfileError, setAuthenticatedProfileError] = useState("");
  const [friendRequests, setFriendRequests] = useState<C19FriendRequest[]>([]);
  const [friends, setFriends] = useState<C19Friend[]>([]);
  const [blocks, setBlocks] = useState<C19Block[]>([]);
  const [conversations, setConversations] = useState<C19ConversationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [search, setSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState("all");
  const [affiliationByUser, setAffiliationByUser] = useState<Record<number, string>>(
    {},
  );
  const [requestMessageByUser, setRequestMessageByUser] = useState<
    Record<number, string>
  >({});
  const [groupTitle, setGroupTitle] = useState("");
  const [groupUserIds, setGroupUserIds] = useState<Set<number>>(() => new Set());
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [conversationDetail, setConversationDetail] =
    useState<C19Conversation | null>(null);
  const [conversationSettings, setConversationSettings] =
    useState<C19ConversationSettings | null>(null);
  const [detailError, setDetailError] = useState("");
  const [renameTitle, setRenameTitle] = useState("");
  const [inviteUserId, setInviteUserId] = useState("");

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
          for (const affiliation of activeAffiliations(profile)) {
            next[affiliation.org_id] = affiliation.org_name;
          }
        }
        return next;
      });
      setAffiliationByUser((current) => {
        const next = { ...current };
        for (const profile of directoryPage.items) {
          const affiliations = activeAffiliations(profile);
          if (affiliations.length === 1 && !next[profile.user_id]) {
            next[profile.user_id] = affiliations[0].affiliation_id;
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
          ? errorMessage(failures[0].reason, "C19 控制数据加载失败。")
          : `${failures.length} 组控制数据暂未同步，其余内容仍可操作。`,
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
        const affiliations = activeAffiliations(profile);
        if (affiliations.length === 1) {
          setAffiliationByUser((current) => ({
            ...current,
            [profile.user_id]: current[profile.user_id] || affiliations[0].affiliation_id,
          }));
        }
      })
      .catch((error) => {
        if (!active) return;
        setAuthenticatedProfile(null);
        setAuthenticatedProfileError(
          errorMessage(error, "当前用户的 C19 通讯身份读取失败。"),
        );
      });
    return () => {
      active = false;
    };
  }, [user]);

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
              for (const affiliation of activeAffiliations(profile)) {
                next[affiliation.org_id] = affiliation.org_name;
              }
            }
            return next;
          });
          setAffiliationByUser((current) => {
            const next = { ...current };
            for (const profile of page.items) {
              const affiliations = activeAffiliations(profile);
              if (affiliations.length === 1 && !next[profile.user_id]) {
                next[profile.user_id] = affiliations[0].affiliation_id;
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

  const profileByUserId = useMemo(
    () => new Map(directory.map((profile) => [profile.user_id, profile])),
    [directory],
  );
  const selfProfile =
    authenticatedProfile ?? (user ? profileByUserId.get(user.id) ?? null : null);
  const selfAffiliationId = user ? affiliationByUser[user.id] ?? "" : "";
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
  const organizations = useMemo(() => {
    return Object.entries(knownOrganizations).sort((left, right) =>
      left[1].localeCompare(right[1], "zh-CN"),
    );
  }, [knownOrganizations]);
  const filteredDirectory = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return directory.filter((profile) => {
      const affiliations = activeAffiliations(profile);
      if (
        orgFilter !== "all" &&
        !affiliations.some((affiliation) => affiliation.org_id === orgFilter)
      ) {
        return false;
      }
      if (!normalizedSearch) return true;
      const haystack = [
        profile.display_name,
        profile.bio ?? "",
        ...affiliations.flatMap((affiliation) => [
          affiliation.org_name,
          affiliation.role,
        ]),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [directory, orgFilter, search]);

  const participantFor = useCallback(
    (profile: C19Profile): C19ParticipantInput | null => {
      const affiliationId = affiliationByUser[profile.user_id];
      if (!affiliationId) return null;
      return { affiliation_id: affiliationId, user_id: profile.user_id };
    },
    [affiliationByUser],
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
        setActionError(errorMessage(error, "C19 控制操作未完成。"));
      } finally {
        setBusyKey("");
      }
    },
    [busyKey, loadControlData],
  );

  const startDirectConversation = useCallback(
    (profile: C19Profile) => {
      if (!selfProfile) {
        setActionError("当前用户尚未生成 C19 通讯身份。");
        return;
      }
      const actor = participantFor(selfProfile);
      const peer = participantFor(profile);
      if (!actor || !peer) {
        setActionError("创建会话前必须明确选择双方的组织身份。");
        return;
      }
      void runAction(
        `direct:${profile.user_id}`,
        `已创建或打开与 ${profile.display_name} 的会话，可在会话列表中开始聊天。`,
        () =>
          createC19DirectConversation({
            actor_affiliation_id: actor.affiliation_id,
            peer_affiliation_id: peer.affiliation_id,
            peer_user_id: peer.user_id,
          }),
      );
    },
    [participantFor, runAction, selfProfile],
  );

  const submitGroup = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!selfProfile) {
        setActionError("当前用户尚未生成 C19 通讯身份。");
        return;
      }
      const actor = participantFor(selfProfile);
      const members = [...groupUserIds].flatMap((userId) => {
        const profile = profileByUserId.get(userId);
        const participant = profile ? participantFor(profile) : null;
        return participant ? [participant] : [];
      });
      if (!actor) {
        setActionError("建群前必须明确选择自己的组织身份。");
        return;
      }
      if (members.length !== groupUserIds.size) {
        setActionError("每位多组织群成员都必须明确选择加入群组的组织身份。");
        return;
      }
      if (members.length < 2) {
        setActionError("群组至少还需要选择两位成员。所有参与者总数不得少于三人。");
        return;
      }
      const title = groupTitle.trim();
      if (!title) {
        setActionError("请填写群组名称。");
        return;
      }
      void runAction("create-group", "群组控制记录已创建。", async () => {
        await createC19Group({
          actor_affiliation_id: actor.affiliation_id,
          members,
          title,
        });
        setGroupTitle("");
        setGroupUserIds(new Set());
      });
    },
    [
      groupTitle,
      groupUserIds,
      participantFor,
      profileByUserId,
      runAction,
      selfProfile,
    ],
  );

  const loadConversationDetail = useCallback(async (conversationId: string) => {
    setSelectedConversationId(conversationId);
    setConversationDetail(null);
    setConversationSettings(null);
    setDetailError("");
    try {
      const [conversation, settings] = await Promise.all([
        getC19Conversation(conversationId),
        getC19ConversationSettings(conversationId),
      ]);
      setConversationDetail(conversation);
      setConversationSettings(settings);
      setRenameTitle(conversation.title ?? "");
    } catch (error) {
      setDetailError(errorMessage(error, "会话控制详情加载失败。"));
    }
  }, []);

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

  return (
    <section className={styles.workspace} aria-labelledby="c19-title">
      <header className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>C19 · 隐藏控制工作台</span>
          <h2 id="c19-title">跨组织通讯控制台</h2>
          <p>管理跨组织通讯关系，并通过可迁移的记录服务交换文字与 Emoji。</p>
        </div>
        <div className={styles.heroActions}>
          <span className={styles.stageBadge}>第三阶段 · 消息运行时</span>
          <button
            className={styles.secondaryButton}
            disabled={isLoading}
            onClick={() => void loadControlData()}
            type="button"
          >
            <RefreshCcw aria-hidden="true" size={16} />
            {isLoading ? "同步中" : "刷新"}
          </button>
        </div>
      </header>

      <div className={styles.storageNotice} role="status">
        <MessageSquareLock aria-hidden="true" size={22} />
        <div>
          <strong>文字与 Emoji 已接入可迁移的独立记录服务</strong>
          <span>图片、文件和朋友圈仍未开放；本页面不暴露存储地址、VPS 配置或凭据。</span>
        </div>
      </div>

      {selfProfile ? (
        <section className={styles.identityBar} aria-labelledby="identity-title">
          <div>
            <span className={styles.identityIcon}>
              <ShieldCheck aria-hidden="true" size={18} />
            </span>
            <div>
              <strong id="identity-title">本次控制操作身份</strong>
              <span>{selfProfile.display_name}</span>
            </div>
          </div>
          <IdentitySelect
            compact
            label="组织身份"
            onChange={(affiliationId) =>
              setAffiliationByUser((current) => ({
                ...current,
                [selfProfile.user_id]: affiliationId,
              }))
            }
            profile={selfProfile}
            value={selfAffiliationId}
          />
        </section>
      ) : !isLoading ? (
        <div className={styles.warning} role="alert">
          当前登录用户不在 C19 通讯录中，创建会话与群组已安全禁用。
        </div>
      ) : null}

      {loadError ? <div className={styles.warning} role="alert">{loadError}</div> : null}
      {authenticatedProfileError ? (
        <div className={styles.warning} role="alert">{authenticatedProfileError}</div>
      ) : null}
      {actionError ? <div className={styles.error} role="alert">{actionError}</div> : null}
      {notice ? <div className={styles.success} role="status">{notice}</div> : null}

      <nav aria-label="C19 功能区" className={styles.tabs}>
        {(
          [
            ["contacts", "全局通讯录", ContactRound],
            ["relationships", "好友与拉黑", ShieldCheck],
            ["conversations", "会话与群组", UsersRound],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            aria-current={activeTab === key ? "page" : undefined}
            className={activeTab === key ? styles.activeTab : ""}
            key={key}
            onClick={() => setActiveTab(key)}
            type="button"
          >
            <Icon aria-hidden="true" size={17} />
            {label}
          </button>
        ))}
      </nav>

      {isLoading && directory.length === 0 ? (
        <div className={styles.loading} role="status">
          正在读取 C19 控制元数据…
        </div>
      ) : null}

      {activeTab === "contacts" ? (
        <div className={styles.panel}>
          <div className={styles.panelHeading}>
            <div>
              <h3>所有组织成员</h3>
              <p>
                {directoryCount} 位成员符合当前条件
                {directoryCount > LOAD_LIMIT ? `，当前显示前 ${LOAD_LIMIT} 位` : ""}。
              </p>
            </div>
            <label className={styles.search}>
              <Search aria-hidden="true" size={16} />
              <input
                aria-label="搜索 C19 通讯录"
                onChange={(event) => setSearch(event.target.value)}
                placeholder="姓名、组织或角色"
                type="search"
                value={search}
              />
              {isDirectorySearching ? <span className={styles.searching}>同步中</span> : null}
            </label>
          </div>

          <div className={styles.orgFilters} aria-label="按组织筛选">
            <button
              className={orgFilter === "all" ? styles.selectedFilter : ""}
              onClick={() => setOrgFilter("all")}
              type="button"
            >
              全部组织
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

          {filteredDirectory.length === 0 ? (
            <EmptyState>没有匹配的内部成员。</EmptyState>
          ) : (
            <div className={styles.contactGrid}>
              {filteredDirectory.map((profile) => {
                const isSelf = profile.user_id === user?.id;
                const isBlocked = blockedUserIds.has(profile.user_id);
                const isFriend = friendUserIds.has(profile.user_id);
                const isPending = pendingRequestUserIds.has(profile.user_id);
                const peerAffiliationId = affiliationByUser[profile.user_id] ?? "";
                const identityReady = Boolean(selfAffiliationId && peerAffiliationId);
                return (
                  <article className={styles.contactCard} key={profile.user_id}>
                    <div className={styles.contactHeader}>
                      <ProfileAvatar profile={profile} />
                      <div>
                        <strong>{profile.display_name}</strong>
                        <span>{profile.bio || "内部成员"}</span>
                      </div>
                      {isSelf ? <span className={styles.selfBadge}>本人</span> : null}
                    </div>
                    <div className={styles.affiliationTags}>
                      {activeAffiliations(profile).map((affiliation) => (
                        <span key={affiliation.affiliation_id}>
                          {affiliation.org_name}
                          <small>{affiliation.role}</small>
                        </span>
                      ))}
                    </div>
                    {!isSelf ? (
                      <IdentitySelect
                        compact
                        label="对方加入身份"
                        onChange={(affiliationId) =>
                          setAffiliationByUser((current) => ({
                            ...current,
                            [profile.user_id]: affiliationId,
                          }))
                        }
                        profile={profile}
                        value={peerAffiliationId}
                      />
                    ) : null}
                    {!isSelf ? (
                      <div className={styles.cardActions}>
                        <button
                          disabled={!identityReady || isBlocked || Boolean(busyKey)}
                          onClick={() => startDirectConversation(profile)}
                          title={
                            identityReady
                              ? "仅创建会话控制记录，不发送消息"
                              : "请先明确选择双方组织身份"
                          }
                          type="button"
                        >
                          <ContactRound aria-hidden="true" size={15} />
                          建立会话
                        </button>
                        <button
                          disabled={
                            isFriend || isPending || isBlocked || Boolean(busyKey)
                          }
                          onClick={() =>
                            void runAction(
                              `friend:${profile.user_id}`,
                              `已向 ${profile.display_name} 提交好友申请。`,
                              () =>
                                createC19FriendRequest({
                                  addressee_user_id: profile.user_id,
                                  request_message:
                                    requestMessageByUser[profile.user_id]?.trim() ||
                                    undefined,
                                }),
                            )
                          }
                          type="button"
                        >
                          <UserPlus aria-hidden="true" size={15} />
                          {isFriend ? "已是好友" : isPending ? "申请处理中" : "加好友"}
                        </button>
                        <button
                          className={styles.dangerButton}
                          disabled={isBlocked || Boolean(busyKey)}
                          onClick={() =>
                            void runAction(
                              `block:${profile.user_id}`,
                              `已将 ${profile.display_name} 加入黑名单。`,
                              () => createC19Block(profile.user_id),
                            )
                          }
                          type="button"
                        >
                          <Ban aria-hidden="true" size={15} />
                          {isBlocked ? "已拉黑" : "拉黑"}
                        </button>
                      </div>
                    ) : null}
                    {!isSelf && !isFriend && !isPending && !isBlocked ? (
                      <input
                        aria-label={`给 ${profile.display_name} 的好友申请说明`}
                        className={styles.requestNote}
                        maxLength={500}
                        onChange={(event) =>
                          setRequestMessageByUser((current) => ({
                            ...current,
                            [profile.user_id]: event.target.value,
                          }))
                        }
                        placeholder="好友申请说明（可选）"
                        value={requestMessageByUser[profile.user_id] ?? ""}
                      />
                    ) : null}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      ) : null}

      {activeTab === "relationships" ? (
        <div className={styles.relationshipColumns}>
          <section className={styles.panel}>
            <div className={styles.panelHeading}>
              <div>
                <h3>好友申请</h3>
                <p>申请操作由当前登录身份决定。</p>
              </div>
              <span className={styles.countBadge}>{friendRequests.length}</span>
            </div>
            {friendRequests.length === 0 ? (
              <EmptyState>暂无好友申请。</EmptyState>
            ) : (
              <div className={styles.stack}>
                {friendRequests.map((request) => {
                  const incoming = request.addressee.user_id === user?.id;
                  const otherUserId = incoming
                    ? request.requester.user_id
                    : request.addressee.user_id;
                  const profile = profileByUserId.get(otherUserId);
                  const profileName = incoming
                    ? request.requester.display_name
                    : request.addressee.display_name;
                  return (
                    <article className={styles.rowCard} key={request.request_id}>
                      <div>
                        <strong>{profile?.display_name ?? profileName}</strong>
                        <span>
                          {incoming ? "向你发起申请" : "你发出的申请"} · {request.status}
                        </span>
                        {request.request_message ? <p>{request.request_message}</p> : null}
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
                                    () => actOnC19FriendRequest(request.request_id, "accept"),
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
                                    () => actOnC19FriendRequest(request.request_id, "reject"),
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
                                  () => actOnC19FriendRequest(request.request_id, "cancel"),
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
          </section>

          <section className={styles.panel}>
            <div className={styles.panelHeading}>
              <div><h3>好友</h3><p>好友关系不授予组织业务数据权限。</p></div>
              <span className={styles.countBadge}>{friends.length}</span>
            </div>
            {friends.length === 0 ? (
              <EmptyState>暂无好友关系。</EmptyState>
            ) : (
              <div className={styles.stack}>
                {friends.map((friend) => {
                  const profile = friend.profile;
                  return (
                    <article className={styles.rowCard} key={friend.relationship_id}>
                      <div>
                        <strong>{profile.display_name}</strong>
                        <span>建立于 {readableDate(friend.established_at)}</span>
                      </div>
                      <button
                        className={styles.dangerButton}
                        disabled={Boolean(busyKey)}
                        onClick={() =>
                          void runAction(
                            `remove-friend:${friend.profile.user_id}`,
                            "好友关系已解除。",
                            () => removeC19Friend(friend.profile.user_id),
                          )
                        }
                        type="button"
                      >
                        <UserMinus aria-hidden="true" size={15} />解除
                      </button>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className={styles.panel}>
            <div className={styles.panelHeading}>
              <div><h3>我的黑名单</h3><p>黑名单仅对当前用户可见。</p></div>
              <span className={styles.countBadge}>{blocks.length}</span>
            </div>
            {blocks.length === 0 ? (
              <EmptyState>黑名单为空。</EmptyState>
            ) : (
              <div className={styles.stack}>
                {blocks.map((block) => {
                  const profile = block.profile;
                  return (
                    <article className={styles.rowCard} key={block.block_id}>
                      <div>
                        <strong>{profile.display_name}</strong>
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
                  );
                })}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {activeTab === "conversations" ? (
        <div className={styles.conversationLayout}>
          <div className={styles.conversationRail}>
            <section className={styles.panel}>
              <div className={styles.panelHeading}>
                <div><h3>会话</h3><p>选择会话读取持久化消息并开始聊天。</p></div>
                <span className={styles.countBadge}>{conversations.length}</span>
              </div>
              {conversations.length === 0 ? (
                <EmptyState>暂无会话控制记录。</EmptyState>
              ) : (
                <div className={styles.conversationList}>
                  {conversations.map((conversation) => (
                    <button
                      className={
                        selectedConversationId === conversation.conversation_id
                          ? styles.selectedConversation
                          : ""
                      }
                      key={conversation.conversation_id}
                      onClick={() => void loadConversationDetail(conversation.conversation_id)}
                      type="button"
                    >
                      <span>
                        {conversation.type === "group" ? (
                          <UsersRound aria-hidden="true" size={17} />
                        ) : (
                          <ContactRound aria-hidden="true" size={17} />
                        )}
                      </span>
                      <div>
                        <strong>
                          {conversation.title ||
                            (conversation.type === "group" ? "未命名群组" : "单聊会话")}
                        </strong>
                        <small>
                          {conversation.type === "group" ? "群组" : "单聊"} · {conversation.status}
                        </small>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className={styles.panel}>
              <div className={styles.panelHeading}>
                <div><h3>建立群组</h3><p>选择至少两位其他成员。</p></div>
                <UserPlus aria-hidden="true" size={19} />
              </div>
              <form className={styles.groupForm} onSubmit={submitGroup}>
                <label className={styles.field}>
                  <span>群组名称</span>
                  <input
                    maxLength={255}
                    onChange={(event) => setGroupTitle(event.target.value)}
                    placeholder="例如：跨组织选品协作"
                    value={groupTitle}
                  />
                </label>
                <div className={styles.memberPicker}>
                  {directory
                    .filter((profile) => profile.user_id !== user?.id)
                    .map((profile) => {
                      const selected = groupUserIds.has(profile.user_id);
                      return (
                        <div className={styles.memberOption} key={profile.user_id}>
                          <label>
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
                            <span>{profile.display_name}</span>
                          </label>
                          {selected ? (
                            <IdentitySelect
                              compact
                              label="加入身份"
                              onChange={(affiliationId) =>
                                setAffiliationByUser((current) => ({
                                  ...current,
                                  [profile.user_id]: affiliationId,
                                }))
                              }
                              profile={profile}
                              value={affiliationByUser[profile.user_id] ?? ""}
                            />
                          ) : null}
                        </div>
                      );
                    })}
                </div>
                <button
                  className={styles.primaryButton}
                  disabled={Boolean(busyKey) || !selfAffiliationId}
                  type="submit"
                >
                  <UsersRound aria-hidden="true" size={16} />
                  创建群组控制记录
                </button>
              </form>
            </section>
          </div>

          <section className={`${styles.panel} ${styles.detailPanel}`}>
            {!selectedConversationId ? (
              <EmptyState>选择一个会话读取消息、成员与设置。</EmptyState>
            ) : detailError ? (
              <div className={styles.error} role="alert">{detailError}</div>
            ) : !conversationDetail || !conversationSettings ? (
              <div className={styles.loading} role="status">正在读取会话控制详情…</div>
            ) : (
              <div className={styles.conversationDetailStack}>
                {user ? (
                  <C19ChatPanel
                    conversation={conversationDetail}
                    profiles={directory}
                    userId={user.id}
                  />
                ) : null}
                <ConversationControlDetail
                  affiliationByUser={affiliationByUser}
                  canDissolveGroup={canDissolveGroup}
                  canManageGroup={canManageGroup}
                  conversation={conversationDetail}
                  directory={directory}
                  inviteUserId={inviteUserId}
                  onAddMember={() => {
                    const profile = profileByUserId.get(Number(inviteUserId));
                    const participant = profile ? participantFor(profile) : null;
                    if (!participant) {
                      setActionError("邀请多组织成员前必须明确选择其加入身份。");
                      return;
                    }
                    void runAction(
                      "add-member",
                      "群成员已加入控制记录。",
                      async () => {
                        const updated = await addC19GroupMembers(
                          conversationDetail.conversation_id,
                          { members: [participant] },
                        );
                        setConversationDetail(updated);
                        setInviteUserId("");
                      },
                    );
                  }}
                  onDissolve={() => {
                    if (!window.confirm("确定解散这个群组控制记录吗？")) return;
                    void runAction("dissolve", "群组控制记录已解散。", async () => {
                      await dissolveC19Group(conversationDetail.conversation_id);
                      setSelectedConversationId("");
                      setConversationDetail(null);
                    });
                  }}
                  onIdentityChange={(userId, affiliationId) =>
                    setAffiliationByUser((current) => ({
                      ...current,
                      [userId]: affiliationId,
                    }))
                  }
                  onInviteUserChange={setInviteUserId}
                  onLeave={() =>
                    void runAction("leave", "你已退出群组控制记录。", async () => {
                      await leaveC19Group(conversationDetail.conversation_id);
                      setSelectedConversationId("");
                      setConversationDetail(null);
                    })
                  }
                  onRemoveMember={(member) =>
                    void runAction(
                      `remove-member:${member.user_id}`,
                      "群成员已移除。",
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
                    void runAction("rename", "群组名称已更新。", async () => {
                      const updated = await updateC19Group(
                        conversationDetail.conversation_id,
                        { title: renameTitle.trim() },
                      );
                      setConversationDetail(updated);
                    });
                  }}
                  onRenameTitleChange={setRenameTitle}
                  onSettingsChange={updateSettings}
                  onTransferOwner={(member) =>
                    void runAction("transfer-owner", "群主已转让。", async () => {
                      const updated = await transferC19GroupOwner(
                        conversationDetail.conversation_id,
                        { new_owner_user_id: member.user_id },
                      );
                      setConversationDetail(updated);
                    })
                  }
                  renameTitle={renameTitle}
                  selfUserId={user?.id ?? null}
                  settings={conversationSettings}
                />
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}

function ConversationControlDetail({
  affiliationByUser,
  canDissolveGroup,
  canManageGroup,
  conversation,
  directory,
  inviteUserId,
  onAddMember,
  onDissolve,
  onIdentityChange,
  onInviteUserChange,
  onLeave,
  onRemoveMember,
  onRename,
  onRenameTitleChange,
  onSettingsChange,
  onTransferOwner,
  renameTitle,
  selfUserId,
  settings,
}: {
  affiliationByUser: Record<number, string>;
  canDissolveGroup: boolean;
  canManageGroup: boolean;
  conversation: C19Conversation;
  directory: C19Profile[];
  inviteUserId: string;
  onAddMember: () => void;
  onDissolve: () => void;
  onIdentityChange: (userId: number, affiliationId: string) => void;
  onInviteUserChange: (userId: string) => void;
  onLeave: () => void;
  onRemoveMember: (member: C19ConversationMember) => void;
  onRename: (event: FormEvent<HTMLFormElement>) => void;
  onRenameTitleChange: (title: string) => void;
  onSettingsChange: (patch: Partial<C19ConversationSettings>) => void;
  onTransferOwner: (member: C19ConversationMember) => void;
  renameTitle: string;
  selfUserId: number | null;
  settings: C19ConversationSettings;
}) {
  const memberIds = new Set(conversation.members.map((member) => member.user_id));
  const availableProfiles = directory.filter((profile) => !memberIds.has(profile.user_id));
  const inviteProfile = availableProfiles.find(
    (profile) => profile.user_id === Number(inviteUserId),
  );

  return (
    <div className={styles.detailContent}>
      <div className={styles.detailHeading}>
        <div>
          <span>{conversation.type === "group" ? "群组" : "单聊"}</span>
          <h3>{conversation.title || "会话控制记录"}</h3>
          <p>{conversation.conversation_id}</p>
        </div>
        <span className={styles.statusBadge}>{conversation.status}</span>
      </div>

      <section className={styles.settingsSection}>
        <h4><Settings2 aria-hidden="true" size={17} />我的会话设置</h4>
        <div className={styles.settingGrid}>
          <label>
            <input
              checked={settings.is_pinned}
              onChange={(event) => onSettingsChange({ is_pinned: event.target.checked })}
              type="checkbox"
            />
            <Pin aria-hidden="true" size={15} />置顶
          </label>
          <label>
            <input
              checked={settings.is_muted}
              onChange={(event) => onSettingsChange({ is_muted: event.target.checked })}
              type="checkbox"
            />
            <VolumeX aria-hidden="true" size={15} />静音
          </label>
          <label>
            <input
              checked={settings.is_archived}
              onChange={(event) => onSettingsChange({ is_archived: event.target.checked })}
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

      <section className={styles.membersSection}>
        <div className={styles.sectionHeading}>
          <h4><UsersRound aria-hidden="true" size={17} />成员</h4>
          <span>{conversation.members.length}</span>
        </div>
        <div className={styles.stack}>
          {conversation.members.map((member) => {
            const profile = directory.find((item) => item.user_id === member.user_id);
            return (
              <article
                className={styles.memberRow}
                key={`${conversation.conversation_id}:${member.user_id}`}
              >
                <div>
                  <strong>{profile?.display_name ?? `成员 #${member.user_id}`}</strong>
                  <span>{member.role} · {member.status} · {member.org_id}</span>
                </div>
                {conversation.type === "group" && member.user_id !== selfUserId ? (
                  <div className={styles.inlineActions}>
                    {canDissolveGroup && member.status === "active" ? (
                      <button onClick={() => onTransferOwner(member)} type="button">
                        转让群主
                      </button>
                    ) : null}
                    {canManageGroup && member.status === "active" ? (
                      <button
                        className={styles.dangerButton}
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

      {conversation.type === "group" ? (
        <section className={styles.groupControls}>
          {canManageGroup ? (
            <>
              <form onSubmit={onRename}>
                <label className={styles.field}>
                  <span>群组名称</span>
                  <input
                    maxLength={255}
                    onChange={(event) => onRenameTitleChange(event.target.value)}
                    value={renameTitle}
                  />
                </label>
                <button type="submit">保存名称</button>
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
                {inviteProfile ? (
                  <IdentitySelect
                    compact
                    label="加入身份"
                    onChange={(affiliationId) =>
                      onIdentityChange(inviteProfile.user_id, affiliationId)
                    }
                    profile={inviteProfile}
                    value={affiliationByUser[inviteProfile.user_id] ?? ""}
                  />
                ) : null}
                <button disabled={!inviteProfile} onClick={onAddMember} type="button">
                  邀请加入
                </button>
              </div>
            </>
          ) : null}
          <div className={styles.destructiveActions}>
            <button onClick={onLeave} type="button">退出群组</button>
            {canDissolveGroup ? (
              <button className={styles.dangerButton} onClick={onDissolve} type="button">
                解散群组
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      <div className={styles.readOnlyFooter}>
        <MessageSquareLock aria-hidden="true" size={16} />
        会话管理与文字消息已开放；图片、文件、朋友圈及音视频仍未开放。
      </div>
    </div>
  );
}
