"use client";

import {
  Bot,
  Eye,
  Fingerprint,
  KeyRound,
  LoaderCircle,
  Plus,
  Power,
  PowerOff,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserRoundCog,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { McpSecretBanner } from "@/components/mcp-secret-banner";
import { formatDisplayName } from "@/components/profile-provider";

import styles from "./user-management-panel.module.css";
import { isApiAbortError } from "@/lib/api";
import {
  canManageUsersForRole,
  isOrgAdminLikeRole,
  isOwnerRole,
  isSuperAdminRole,
  normalizeRole,
} from "@/lib/roles";
import {
  MANAGED_USER_ROLES,
  USERS_PAGE_LIMIT,
  createUser,
  disableUser,
  disableUserMcpToken,
  enableUser,
  enableUserMcpToken,
  formatUsersApiError,
  getUser,
  isManagedUserRole,
  listOrganizations,
  listUserRoles,
  listUsers,
  resetUserMcpToken,
  type McpTokenIssued,
  purgeUser,
  registerBot,
  resetUserPassword,
  updateUser,
  type ManagedUser,
  type ManagedUserRole,
  type OrganizationOption,
  type UserRoleMetadata,
  type UserRolesResponse,
  managedUserDisplayName,
} from "@/lib/users-api";

const PASSWORD_LENGTH_MESSAGE =
  "密码长度必须为 12 到 256 个字符。";
const FALLBACK_ROLE_METADATA: UserRoleMetadata[] = [
  {
    assignable: true,
    c04_status: "bootstrap_only",
    description: "拥有全部权限。",
    human_or_agent: "human",
    label: "owner",
    name: "owner",
  },
  {
    assignable: true,
    c04_status: "user_management_admin_role",
    description: "管理所属组织。",
    human_or_agent: "human",
    label: "组织管理员",
    name: "super_admin",
  },
  {
    assignable: true,
    c04_status: "assignable_admin_role",
    description: "管理授权范围内的账号和模块。",
    human_or_agent: "human",
    label: "管理员",
    name: "admin",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "查看允许访问的内容。",
    human_or_agent: "human",
    label: "查看员",
    name: "viewer",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "处理允许访问的业务。",
    human_or_agent: "human",
    label: "操作员",
    name: "operator",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "审核允许访问的业务。",
    human_or_agent: "human",
    label: "审核员",
    name: "reviewer",
  },
];
const FALLBACK_ROLE_METADATA_BY_NAME = new Map(
  FALLBACK_ROLE_METADATA.map((role) => [role.name, role]),
);
const FALLBACK_ASSIGNABLE_ROLES = MANAGED_USER_ROLES.map((role) =>
  FALLBACK_ROLE_METADATA_BY_NAME.get(role),
).filter((role): role is UserRoleMetadata => Boolean(role));

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "暂无记录";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无记录";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function validatePassword(password: string) {
  if (password.length < 12 || password.length > 256) {
    return PASSWORD_LENGTH_MESSAGE;
  }
  return "";
}

function roleLabel(role: string) {
  const normalizedRole = normalizeRole(role);
  const labels: Record<string, string> = {
    admin: "管理员",
    operator: "操作员",
    owner: "owner",
    reviewer: "审核员",
    super_admin: "组织管理员",
    viewer: "查看员",
  };
  return labels[normalizedRole] ?? "成员";
}

function roleDescription(role: string) {
  const normalizedRole = normalizeRole(role);
  const descriptions: Record<string, string> = {
    admin: "管理授权范围内的账号和模块。",
    operator: "处理已授权的业务操作。",
    owner: "拥有全部权限。",
    reviewer: "审核已授权的业务。",
    super_admin: "管理所属组织内的账号和功能。",
    viewer: "查看已授权的内容。",
  };
  return descriptions[normalizedRole] ?? "按授权范围访问工作台。";
}

export function UserManagementPanel() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [userCount, setUserCount] = useState(0);
  const [userOffset, setUserOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [roleCatalog, setRoleCatalog] =
    useState<UserRolesResponse | null>(null);
  const [isRoleCatalogLoading, setIsRoleCatalogLoading] = useState(true);
  const [roleCatalogError, setRoleCatalogError] = useState("");
  const [organizations, setOrganizations] = useState<OrganizationOption[]>(
    [],
  );
  const [isOrganizationsLoading, setIsOrganizationsLoading] =
    useState(true);
  const [organizationsError, setOrganizationsError] = useState("");
  const [listError, setListError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  // MCP 个人钥匙:重置后明文只显示这一次(与初始密码同一做法),由管理者转交。
  const [mcpIssued, setMcpIssued] = useState<
    { username: string; secret: string; initialPassword?: string | null; mac?: string; windows?: string } | null
  >(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [expandedUser, setExpandedUser] = useState<ManagedUser | null>(null);
  const [detailRole, setDetailRole] =
    useState<ManagedUserRole>("viewer");
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [createUsername, setCreateUsername] = useState("");
  // 注册机器人(2026-08-22 拍板:以后的机器人必须在这里注册,带清晰标记和所属组织)
  const [botUsername, setBotUsername] = useState("");
  const [botDisplayName, setBotDisplayName] = useState("");
  const [botJobTitle, setBotJobTitle] = useState("");
  const [botOrganizationId, setBotOrganizationId] = useState("");
  const [botBio, setBotBio] = useState("");
  const [botPassword, setBotPassword] = useState("");
  const [createJobTitle, setCreateJobTitle] = useState("");
  const [createOrganizationId, setCreateOrganizationId] = useState("");
  const [createRole, setCreateRole] =
    useState<ManagedUserRole>("viewer");
  const [createOpen, setCreateOpen] = useState(false);
  const [listCollapsed, setListCollapsed] = useState(false);

  const userCanManageUsers = canManageUsersForRole(currentUser?.role);
  const isBusy = pendingAction !== null;

  const loadRoleCatalog = useCallback(async () => {
    if (!userCanManageUsers) {
      setRoleCatalog(null);
      setRoleCatalogError("");
      setIsRoleCatalogLoading(false);
      return;
    }

    setIsRoleCatalogLoading(true);
    setRoleCatalogError("");

    try {
      setRoleCatalog(await listUserRoles());
    } catch (error) {
      setRoleCatalogError(
        formatUsersApiError(
          error,
          "角色数据暂未同步，请重试。",
        ),
      );
    } finally {
      setIsRoleCatalogLoading(false);
    }
  }, [userCanManageUsers]);

  const loadOrganizations = useCallback(async () => {
    setIsOrganizationsLoading(true);
    setOrganizationsError("");
    try {
      const result = await listOrganizations();
      setOrganizations(result.items);
    } catch (error) {
      if (isApiAbortError(error)) {
        try {
          const result = await listOrganizations();
          setOrganizations(result.items);
        } catch (retryError) {
          if (!isApiAbortError(retryError)) {
            setOrganizationsError(
              formatUsersApiError(
                retryError,
                "组织数据暂未同步，请重试。",
              ),
            );
          }
        }
        return;
      }
      setOrganizationsError(
        formatUsersApiError(
          error,
          "组织数据暂未同步，请重试。",
        ),
      );
    } finally {
      setIsOrganizationsLoading(false);
    }
  }, []);

  const loadUsers = useCallback(
    async (showLoading = true, offset = userOffset) => {
      if (showLoading) {
        setIsLoading(true);
      }
      setListError("");

      try {
        const result = await listUsers(USERS_PAGE_LIMIT, offset);
        setUsers(result.items);
        setUserCount(result.count);
        setUserOffset(offset);
      } catch (error) {
        if (isApiAbortError(error)) {
          try {
            const result = await listUsers(USERS_PAGE_LIMIT, offset);
            setUsers(result.items);
            setUserCount(result.count);
            setUserOffset(offset);
          } catch (retryError) {
            if (!isApiAbortError(retryError)) {
              setListError(
                formatUsersApiError(
                  retryError,
                  "用户数据暂未同步，请重试。",
                ),
              );
            }
          }
          return;
        }
        setListError(
          formatUsersApiError(
            error,
            "用户数据暂未同步，请重试。",
          ),
        );
      } finally {
        if (showLoading) {
          setIsLoading(false);
        }
      }
    },
    [userOffset],
  );

  useEffect(() => {
    void loadRoleCatalog();
  }, [loadRoleCatalog]);

  useEffect(() => {
    void loadOrganizations();
  }, [loadOrganizations]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const currentUserOrgId = currentUser?.organization_id ?? null;
  const canAssignRole = useCallback(
    (role: string) => {
      const normalizedRole = normalizeRole(role);
      if (isOwnerRole(currentUser?.role)) {
        return isManagedUserRole(normalizedRole);
      }
      if (isOrgAdminLikeRole(currentUser?.role)) {
        return (
          isManagedUserRole(normalizedRole) &&
          !isOwnerRole(normalizedRole) &&
          !isSuperAdminRole(normalizedRole)
        );
      }
      return false;
    },
    [currentUser?.role],
  );

  const canManageTarget = useCallback(
    (target: ManagedUser | null | undefined) => {
      if (!target) {
        return false;
      }
      if (isOwnerRole(currentUser?.role)) {
        return true;
      }
      if (!isOrgAdminLikeRole(currentUser?.role)) {
        return false;
      }
      if (isOwnerRole(target.role) || isSuperAdminRole(target.role)) {
        return false;
      }
      return (
        Boolean(currentUserOrgId) &&
        target.organization_id === currentUserOrgId
      );
    },
    [currentUser?.role, currentUserOrgId],
  );

  const assignableRoleOptions = useMemo(() => {
    if (!roleCatalog) {
      return roleCatalogError
        ? FALLBACK_ASSIGNABLE_ROLES.filter((role) => canAssignRole(role.name))
        : [];
    }

    return roleCatalog.assignable_roles.filter(
      (role) => role.assignable && canAssignRole(role.name),
    );
  }, [canAssignRole, roleCatalog, roleCatalogError]);

  const assignableRoleNames = useMemo(
    () => new Set(assignableRoleOptions.map((role) => role.name)),
    [assignableRoleOptions],
  );

  const creatableOrganizations = useMemo(() => {
    if (isOwnerRole(currentUser?.role)) {
      return organizations;
    }
    if (isOrgAdminLikeRole(currentUser?.role) && currentUserOrgId) {
      return organizations.filter(
        (organization) => organization.org_id === currentUserOrgId,
      );
    }
    return [];
  }, [currentUser?.role, currentUserOrgId, organizations]);

  useEffect(() => {
    if (assignableRoleOptions.length === 0) {
      return;
    }

    const firstRole = assignableRoleOptions[0].name as ManagedUserRole;
    if (!assignableRoleNames.has(createRole)) {
      setCreateRole(firstRole);
    }
    if (!assignableRoleNames.has(detailRole)) {
      setDetailRole(firstRole);
    }
  }, [
    assignableRoleNames,
    assignableRoleOptions,
    createRole,
    detailRole,
  ]);

  useEffect(() => {
    if (
      creatableOrganizations.length > 0 &&
      !createOrganizationId &&
      !isOwnerRole(createRole)
    ) {
      setCreateOrganizationId(creatableOrganizations[0].org_id);
    }
  }, [creatableOrganizations, createOrganizationId, createRole]);

  const organizationById = useMemo(
    () =>
      new Map(
        organizations.map((organization) => [
          organization.org_id,
          organization,
        ]),
      ),
    [organizations],
  );

  const sortedUsers = useMemo(
    () =>
      [...users].sort((left, right) => {
        if (left.role === "owner" && right.role !== "owner") {
          return -1;
        }
        if (right.role === "owner" && left.role !== "owner") {
          return 1;
        }
        return left.username.localeCompare(right.username);
      }),
    [users],
  );
  function clearActionMessages() {
    setActionError("");
    setActionNotice("");
  }

  async function refreshDetail(userId: number) {
    const detail = await getUser(userId);
    setExpandedUser(detail);
    if (isManagedUserRole(detail.role)) {
      setDetailRole(detail.role);
    }
  }

  async function refreshAfterMutation(userId?: number) {
    await loadUsers(false);
    if (userId && expandedUser?.id === userId) {
      await refreshDetail(userId);
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearActionMessages();
    if (!userCanManageUsers) {
      setActionError("当前账号不能创建用户。");
      return;
    }

    const username = createUsername.trim();
    const jobTitle = createJobTitle.trim();
    if (!username) {
      setActionError("请填写用户名。");
      return;
    }
    if (
      !isManagedUserRole(createRole) ||
      !assignableRoleNames.has(createRole)
    ) {
      setActionError(
        "请选择可分配的角色后再创建账号。",
      );
      return;
    }
    if (!isOwnerRole(createRole) && !createOrganizationId) {
      setActionError("非owner账号必须选择组织。");
      return;
    }

    setPendingAction("create");
    try {
      const created = await createUser({
        job_title: isOwnerRole(createRole) ? null : jobTitle || null,
        organization_id: isOwnerRole(createRole)
          ? null
          : createOrganizationId,
        role: createRole,
        username,
      });
      setActionNotice(`已创建账号：${created.username}。`);
      if (created.initial_password || created.mcp_token_secret) {
        setMcpIssued({
          username: created.username,
          secret: created.mcp_token_secret ?? "",
          initialPassword: created.initial_password ?? null,
        });
      }
      setCreateUsername("");
      setCreateJobTitle("");
      setCreateOrganizationId(
        creatableOrganizations.length > 0
          ? creatableOrganizations[0].org_id
          : "",
      );
      setCreateRole("viewer");
      await refreshAfterMutation(created.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "账号创建未完成，请重试。"),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRegisterBot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearActionMessages();
    if (!isOwnerRole(currentUser?.role)) {
      setActionError("只有 owner 能注册机器人。");
      return;
    }
    const username = botUsername.trim();
    const displayName = botDisplayName.trim();
    const jobTitle = botJobTitle.trim();
    const organizationId = botOrganizationId || creatableOrganizations[0]?.org_id || "";
    if (!username || !displayName || !jobTitle || !organizationId) {
      setActionError("登录名、显示名、岗位、组织都要填。");
      return;
    }
    if (!/^[a-z][a-z0-9_]*$/.test(username)) {
      setActionError("登录名只能是小写字母、数字、下划线，且字母开头。");
      return;
    }
    if (botPassword.length < 12) {
      setActionError("机器人密码至少 12 位（给它的 worker 登录用）。");
      return;
    }
    setPendingAction("register-bot");
    try {
      const created = await registerBot({
        username,
        display_name: displayName,
        job_title: jobTitle,
        organization_id: organizationId,
        bio: botBio.trim() || null,
        password: botPassword,
      });
      setActionNotice(
        `已注册机器人：${displayName}（${created.username}）。把密码写进它的 worker 环境变量后再启动。`,
      );
      setBotUsername("");
      setBotDisplayName("");
      setBotJobTitle("");
      setBotBio("");
      setBotPassword("");
      await refreshAfterMutation(created.id);
    } catch (error) {
      setActionError(formatUsersApiError(error, "机器人注册未完成，请重试。"));
    } finally {
      setPendingAction(null);
    }
  }

  async function handlePurge(target: ManagedUser) {
    clearActionMessages();
    if (!isOwnerRole(currentUser?.role)) {
      setActionError("只有 owner 能删除账号。");
      return;
    }
    if (target.is_active) {
      setActionError("先停用，再删除。");
      return;
    }
    if (
      !window.confirm(
        `彻底删除 ${managedUserDisplayName(target)}？登录会话、组织成员关系、权限、通讯资料都会一起删掉，不可恢复。有业务记录引用的账号会被拒绝。`,
      )
    ) {
      return;
    }
    setPendingAction(`purge-${target.id}`);
    try {
      const result = await purgeUser(target.id);
      setActionNotice(`已删除账号：${result.username}。`);
      if (expandedUser?.id === target.id) {
        setExpandedUser(null);
      }
      await refreshAfterMutation();
    } catch (error) {
      setActionError(formatUsersApiError(error, "删除未完成。有业务记录引用的账号只能停用。"));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleViewDetails(target: ManagedUser) {
    clearActionMessages();
    if (expandedUser?.id === target.id) {
      setExpandedUser(null);
      return;
    }

    setPendingAction(`detail-${target.id}`);
    try {
      await refreshDetail(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "账号详情暂未同步，请重试。"),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleDisable(target: ManagedUser) {
    clearActionMessages();
    if (!canManageTarget(target)) {
      setActionError("当前账号不能管理该用户。");
      return;
    }
    if (target.id === currentUser?.id) {
      setActionError("不能在这里停用当前登录账号。");
      return;
    }
    if (
      !window.confirm(
        `确认停用 ${managedUserDisplayName(target)}？停用后该账号将无法登录。`,
      )
    ) {
      return;
    }

    setPendingAction(`disable-${target.id}`);
    try {
      const updated = await disableUser(target.id);
      setActionNotice(`已停用账号：${managedUserDisplayName(updated)}。`);
      await refreshAfterMutation(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "账号停用未完成，请重试。"),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleEnable(target: ManagedUser) {
    clearActionMessages();
    if (!canManageTarget(target)) {
      setActionError("当前账号不能管理该用户。");
      return;
    }
    if (!window.confirm(`确认启用 ${managedUserDisplayName(target)}？`)) {
      return;
    }

    setPendingAction(`enable-${target.id}`);
    try {
      const updated = await enableUser(target.id);
      setActionNotice(`已启用账号：${managedUserDisplayName(updated)}。`);
      await refreshAfterMutation(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "账号启用未完成，请重试。"),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRoleUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearActionMessages();
    if (!expandedUser) {
      return;
    }
    if (!canManageTarget(expandedUser)) {
      setActionError("当前账号不能管理该用户。");
      return;
    }
    if (expandedUser.id === currentUser?.id) {
      setActionError("不能在这里修改当前登录账号的角色。");
      return;
    }
    if (!isManagedUserRole(expandedUser.role)) {
      setActionError("这里只能调整受管理账号的角色。");
      return;
    }
    if (
      !isManagedUserRole(detailRole) ||
      !assignableRoleNames.has(detailRole)
    ) {
      setActionError(
        "请选择可分配的角色后再保存。",
      );
      return;
    }

    setPendingAction(`role-${expandedUser.id}`);
    try {
      const updated = await updateUser(expandedUser.id, { role: detailRole });
      setActionNotice(`已更新 ${managedUserDisplayName(updated)} 的角色。`);
      await refreshAfterMutation(expandedUser.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "角色更新未完成，请重试。"),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleMcpTokenReset(target: ManagedUser) {
    clearActionMessages();
    if (!canManageTarget(target)) {
      setActionError("当前账号不能管理该用户。");
      return;
    }
    if (
      !window.confirm(
        `确认给 ${managedUserDisplayName(target)} 换一把新的 MCP 钥匙？旧钥匙立刻失效,新钥匙只显示这一次。`,
      )
    ) {
      return;
    }
    setPendingAction(`mcp-reset-${target.id}`);
    try {
      const issued: McpTokenIssued = await resetUserMcpToken(target.id);
      setMcpIssued({
        username: target.username,
        secret: issued.token,
        mac: issued.setup_command_mac,
        windows: issued.setup_command_windows,
      });
      setActionNotice(`已为 ${managedUserDisplayName(target)} 生成新钥匙。`);
      await loadUsers();
    } catch (error) {
      setActionError(formatUsersApiError(error, "重置 MCP 钥匙失败。"));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleMcpTokenToggle(target: ManagedUser) {
    clearActionMessages();
    if (!canManageTarget(target)) {
      setActionError("当前账号不能管理该用户。");
      return;
    }
    const disabled = target.mcp_token?.status === "disabled";
    setPendingAction(`mcp-toggle-${target.id}`);
    try {
      if (disabled) {
        await enableUserMcpToken(target.id);
        setActionNotice(`已启用 ${managedUserDisplayName(target)} 的 MCP 钥匙。`);
      } else {
        await disableUserMcpToken(target.id);
        setActionNotice(`已停用 ${managedUserDisplayName(target)} 的 MCP 钥匙,他的 Codex 立刻连不上。`);
      }
      await loadUsers();
    } catch (error) {
      setActionError(formatUsersApiError(error, "更新 MCP 钥匙状态失败。"));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearActionMessages();
    if (!resetTarget) {
      return;
    }
    if (!canManageTarget(resetTarget)) {
      setActionError("当前账号不能管理该用户。");
      setResetPassword("");
      setResetTarget(null);
      return;
    }
    if (resetTarget.id === currentUser?.id) {
      setActionError("不能在这里重置当前登录账号的密码。");
      setResetPassword("");
      setResetTarget(null);
      return;
    }

    const passwordError = validatePassword(resetPassword);
    if (passwordError) {
      setActionError(passwordError);
      return;
    }

    if (
      !window.confirm(
        `确认重置 ${managedUserDisplayName(resetTarget)} 的密码？原密码将立即失效。`,
      )
    ) {
      return;
    }

    setPendingAction(`reset-${resetTarget.id}`);
    try {
      const updated = await resetUserPassword(
        resetTarget.id,
        resetPassword,
      );
      setActionNotice(`已重置 ${managedUserDisplayName(updated)} 的密码。`);
      setResetTarget(null);
      await refreshAfterMutation(resetTarget.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "密码重置未完成，请重试。"),
      );
    } finally {
      setResetPassword("");
      setPendingAction(null);
    }
  }

  return (
    <section className="users-workspace" aria-label="用户管理">
      {userCanManageUsers ? (
        <>
          <button
            aria-label="关闭创建面板"
            className={`um-scrim ${createOpen ? "on" : ""}`}
            onClick={() => setCreateOpen(false)}
            type="button"
          />
          <aside
            aria-label="创建用户"
            className={`um-drawer um-create ${createOpen ? "on" : ""}`}
          >
            <button
              aria-label="关闭"
              className="um-drawer-x"
              onClick={() => setCreateOpen(false)}
              type="button"
            >
              ×
            </button>
        <form className="users-create-panel" onSubmit={handleCreate}>
        <div className="users-panel-heading">
          <div>
            <span className="eyebrow">账号</span>
            <h3>创建用户</h3>
          </div>
          <UserRoundCog aria-hidden="true" size={24} />
        </div>

        <div className="users-form-grid">
          <label className="field-group">
            <span>用户名</span>
            <span className="input-shell">
              <input
                autoComplete="off"
                disabled={isBusy}
                maxLength={255}
                onChange={(event) => setCreateUsername(event.target.value)}
                placeholder="请输入用户名"
                type="text"
                value={createUsername}
              />
            </span>
          </label>

          <label className="field-group">
            <span>角色</span>
            <select
              className="select-shell"
              disabled={
                isBusy ||
                isRoleCatalogLoading ||
                assignableRoleOptions.length === 0
              }
              onChange={(event) =>
                setCreateRole(event.target.value as ManagedUserRole)
              }
              value={createRole}
            >
              {assignableRoleOptions.map((role) => (
                <option key={role.name} value={role.name}>
                  {roleLabel(role.name)}
                </option>
              ))}
            </select>
            <span className="users-field-note">
              {isRoleCatalogLoading
                ? "正在加载角色"
                : roleCatalogError
                  ? "使用基础角色"
                  : "角色已加载"}
            </span>
          </label>

          <label className="field-group">
            <span>岗位</span>
            <span className="input-shell">
              <input
                autoComplete="organization-title"
                disabled={isBusy || isOwnerRole(createRole)}
                maxLength={255}
                onChange={(event) => setCreateJobTitle(event.target.value)}
                type="text"
                value={isOwnerRole(createRole) ? "" : createJobTitle}
              />
            </span>
          </label>

          <label className="field-group">
            <span>组织</span>
            <select
              className="select-shell"
              disabled={
                isBusy ||
                isOrganizationsLoading ||
                isOwnerRole(createRole) ||
                creatableOrganizations.length === 0
              }
              onChange={(event) =>
                setCreateOrganizationId(event.target.value)
              }
              required={!isOwnerRole(createRole)}
              value={
                isOwnerRole(createRole)
                  ? ""
                  : createOrganizationId
              }
            >
              {isOwnerRole(createRole) ? (
                <option value="">无需选择组织</option>
              ) : creatableOrganizations.length === 0 ? (
                <option value="">暂无可选组织</option>
              ) : (
                creatableOrganizations.map((organization) => (
                  <option
                    key={organization.org_id}
                    value={organization.org_id}
                  >
                    {organization.org_name}
                  </option>
                ))
              )}
            </select>
            <span className="users-field-note">
              {isOrganizationsLoading
                ? "正在加载组织"
                : organizationsError
                  ? organizationsError
                  : "组织已加载"}
            </span>
          </label>
        </div>

        <button
          className="primary-button users-submit-button"
          disabled={
            isBusy ||
            isRoleCatalogLoading ||
            isOrganizationsLoading ||
            assignableRoleOptions.length === 0 ||
            (!isOwnerRole(createRole) && creatableOrganizations.length === 0)
          }
          type="submit"
        >
          {pendingAction === "create" ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          创建用户
        </button>
        </form>

        {isOwnerRole(currentUser?.role) ? (
          <form className="users-create-panel" onSubmit={handleRegisterBot}>
            <div className="users-panel-heading">
              <div>
                <span className="eyebrow">数字员工</span>
                <h3>注册机器人</h3>
              </div>
              <Bot aria-hidden="true" size={24} />
            </div>
            <p className="users-field-note">
              数字员工在这里登记身份：带「机器人」标记、挂一个组织、零权限码。它能做什么由它自己的
              worker 以说话人的身份过各模块的门。
            </p>
            <div className="users-form-grid">
              <label className="field-group">
                <span>登录名</span>
                <span className="input-shell">
                <input
                  autoComplete="off"
                  onChange={(event) => setBotUsername(event.target.value)}
                  placeholder="如 nijing"
                  value={botUsername}
                />
                </span>
              </label>
              <label className="field-group">
                <span>显示名</span>
                <span className="input-shell">
                <input
                  autoComplete="off"
                  onChange={(event) => setBotDisplayName(event.target.value)}
                  placeholder="如 霓旌"
                  value={botDisplayName}
                />
                </span>
              </label>
              <label className="field-group">
                <span>岗位</span>
                <span className="input-shell">
                <input
                  autoComplete="off"
                  onChange={(event) => setBotJobTitle(event.target.value)}
                  placeholder="如 库管员"
                  value={botJobTitle}
                />
                </span>
              </label>
              <label className="field-group">
                <span>所属组织</span>
                <span className="input-shell">
                <select
                  onChange={(event) => setBotOrganizationId(event.target.value)}
                  value={botOrganizationId || creatableOrganizations[0]?.org_id || ""}
                >
                  {creatableOrganizations.map((organization) => (
                    <option key={organization.org_id} value={organization.org_id}>
                      {organization.org_name}
                    </option>
                  ))}
                </select>
                </span>
              </label>
              <label className="field-group">
                <span>简介（通讯里显示）</span>
                <span className="input-shell">
                <input
                  autoComplete="off"
                  onChange={(event) => setBotBio(event.target.value)}
                  value={botBio}
                />
                </span>
              </label>
              <label className="field-group">
                <span>登录密码（≥12 位，给 worker 用）</span>
                <span className="input-shell">
                <input
                  autoComplete="new-password"
                  onChange={(event) => setBotPassword(event.target.value)}
                  type="password"
                  value={botPassword}
                />
                </span>
              </label>
            </div>
            <button
              className="primary-button users-submit-button"
              disabled={isBusy || isOrganizationsLoading || creatableOrganizations.length === 0}
              type="submit"
            >
              {pendingAction === "register-bot" ? (
                <LoaderCircle className="spin" aria-hidden="true" size={17} />
              ) : (
                <Bot aria-hidden="true" size={17} />
              )}
              注册机器人
            </button>
          </form>
        ) : null}
          </aside>
        </>
      ) : null}

      {actionError ? (
        <div className="users-alert users-alert-error" role="alert">
          <ShieldAlert aria-hidden="true" size={18} />
          <span>{actionError}</span>
        </div>
      ) : null}

      {actionNotice ? (
        <div className="users-alert users-alert-success" role="status">
          <span>{actionNotice}</span>
        </div>
      ) : null}

      {mcpIssued ? (
        <McpSecretBanner
          onClose={() => setMcpIssued(null)}
          payload={{
            username: mcpIssued.username,
            secret: mcpIssued.secret,
            initialPassword: mcpIssued.initialPassword,
            setupCommandMac: mcpIssued.mac,
            setupCommandWindows: mcpIssued.windows,
          }}
        />
      ) : null}

      {resetTarget && canManageTarget(resetTarget) ? (
        <>
          <button
            aria-label="取消重置"
            className="um-scrim on"
            onClick={() => {
              setResetTarget(null);
              setResetPassword("");
            }}
            type="button"
          />
        <form className="users-reset-panel um-modal" onSubmit={handleReset}>
          <div>
            <span className="eyebrow">密码重置</span>
            <h3>{managedUserDisplayName(resetTarget)}</h3>
            <p>
              请输入新的临时密码，提交后不会再次显示。
            </p>
          </div>
          <label className="field-group">
            <span>新密码</span>
            <span className="input-shell">
              <input
                autoComplete="new-password"
                disabled={isBusy}
                maxLength={256}
                minLength={12}
                onChange={(event) => setResetPassword(event.target.value)}
                type="password"
                value={resetPassword}
              />
            </span>
          </label>
          <div className="users-inline-actions">
            <button
              className="primary-button"
              disabled={isBusy}
              type="submit"
            >
              <KeyRound aria-hidden="true" size={17} />
              确认重置
            </button>
            <button
              className="secondary-button"
              disabled={isBusy}
              onClick={() => {
                setResetTarget(null);
                setResetPassword("");
              }}
              type="button"
            >
              取消
            </button>
          </div>
        </form>
        </>
      ) : null}

      <div className={`users-list-panel ${listCollapsed ? "collapsed" : ""}`}>
        <div className="users-list-heading">
          <button
            aria-expanded={!listCollapsed}
            className="um-collapse"
            onClick={() => setListCollapsed((value) => !value)}
            title={listCollapsed ? "展开列表" : "收起列表"}
            type="button"
          >
            {listCollapsed ? "▸" : "▾"}
          </button>
          <div>
            <h3>用户列表</h3>
            <p>共 {userCount} 个账号，每页 {USERS_PAGE_LIMIT} 条。</p>
          </div>
          <div className="um-toolbar">
            {userCanManageUsers ? (
              <button
                className="primary-button um-create-btn"
                onClick={() => setCreateOpen(true)}
                type="button"
              >
                <Plus aria-hidden="true" size={17} />
                创建用户
              </button>
            ) : null}
            <button
              className="secondary-button"
              disabled={isBusy || isLoading}
              onClick={() => void loadUsers()}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={17} />
              刷新
            </button>
          </div>
        </div>

        {isLoading && users.length === 0 ? (
          <div className="list-state" aria-label="正在加载用户">
            <div className="skeleton-stack" aria-hidden="true">
              <span className="skeleton-line medium" />
              <span className="skeleton-line" />
              <span className="skeleton-line short" />
            </div>
          </div>
        ) : null}

        {!isLoading && listError ? (
          <div className="list-state list-error" role="alert">
            <div>
              <h2>
                用户数据暂未同步
              </h2>
              <p>{listError || "后端响应暂未返回可用数据。"}</p>
              {users.length > 0 ? (
                <p>正在显示上一次成功加载的用户列表。</p>
              ) : null}
            </div>
            <button
              className="primary-button"
              onClick={() => void loadUsers()}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={17} />
              重试
            </button>
          </div>
        ) : null}

        {(!isLoading || users.length > 0) && (!listError || users.length > 0) ? (
          <>
            <div className="users-table-scroll">
              <table className="users-table">
                <thead>
                  <tr>
                    <th scope="col">用户名</th>
                    <th scope="col">角色</th>
                    <th scope="col">状态</th>
                    <th scope="col">创建时间</th>
                    <th scope="col">更新时间</th>
                    <th scope="col">岗位</th>
                    <th scope="col">组织</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUsers.map((target) => {
                  const isSelf = target.id === currentUser?.id;
                  const canManageRow = canManageTarget(target);
                  const actionDisabled = isBusy || isSelf || !canManageRow;
                  const rowPending =
                    pendingAction?.endsWith(`-${target.id}`) ?? false;
                  const targetOrganization = target.organization_id
                    ? organizationById.get(target.organization_id)
                    : null;
                  const organizationName =
                    targetOrganization?.org_name ??
                    target.organization ??
                    target.organization_id ??
                    "";
                  const showOrgFields = !isOwnerRole(target.role);

                  return (
                    <tr key={target.id}>
                      <td>
                        <strong className="users-name-cell">
                          {target.is_bot ? (
                            <Bot
                              aria-label="机器人"
                              className="users-bot-icon"
                              size={15}
                            />
                          ) : null}
                          {formatDisplayName(
                            target.nickname,
                            target.display_name || target.username,
                          )}
                        </strong>
                        {(target.display_name || target.username) !==
                        target.username ? (
                          <span className="users-login-name">{target.username}</span>
                        ) : null}
                        {isSelf ? <span>当前账号</span> : null}
                      </td>
                      <td>
                        <div className="users-role-cell">
                          <span className="users-role-pill">
                            {roleLabel(target.role)}
                          </span>
                          <span className="users-role-description">
                            {roleDescription(target.role)}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span
                          className={`users-status ${
                            target.is_active
                              ? "users-status-active"
                              : "users-status-disabled"
                          }`}
                        >
                          {target.is_active ? "正常" : "已停用"}
                        </span>
                      </td>
                      <td>{formatDate(target.created_at)}</td>
                      <td>{formatDate(target.updated_at)}</td>
                      <td>{showOrgFields ? target.job_title ?? "" : ""}</td>
                      <td>
                        {showOrgFields
                          ? organizationName
                          : ""}
                      </td>
                      <td>
                        <div className="users-actions">
                          <button
                            className="icon-button"
                            disabled={isBusy}
                            onClick={() => void handleViewDetails(target)}
                            title="查看详情"
                            type="button"
                          >
                            {pendingAction === `detail-${target.id}` ? (
                              <LoaderCircle
                                className="spin"
                                aria-hidden="true"
                                size={17}
                              />
                            ) : (
                              <Eye aria-hidden="true" size={17} />
                            )}
                          </button>

                          {canManageRow && target.is_active ? (
                            <button
                              className="icon-button"
                              disabled={actionDisabled}
                              onClick={() => void handleDisable(target)}
                              title={isSelf ? "不能停用当前账号" : "停用用户"}
                              aria-label="停用用户"
                              type="button"
                            >
                              {pendingAction === `disable-${target.id}` ? (
                                <LoaderCircle
                                  className="spin"
                                  aria-hidden="true"
                                  size={17}
                                />
                              ) : (
                                <PowerOff aria-hidden="true" size={17} />
                              )}
                            </button>
                          ) : canManageRow ? (
                            <button
                              className="icon-button"
                              disabled={isBusy}
                              onClick={() => void handleEnable(target)}
                              title="启用用户"
                              aria-label="启用用户"
                              type="button"
                            >
                              {pendingAction === `enable-${target.id}` ? (
                                <LoaderCircle
                                  className="spin"
                                  aria-hidden="true"
                                  size={17}
                                />
                              ) : (
                                <Power aria-hidden="true" size={17} />
                              )}
                            </button>
                          ) : null}

                          {canManageRow ? (
                            <button
                              className="icon-button"
                              disabled={actionDisabled}
                              onClick={() => {
                                clearActionMessages();
                                setResetTarget(target);
                                setResetPassword("");
                              }}
                              title={isSelf ? "不能重置当前账号密码" : "重置密码"}
                              aria-label="重置密码"
                              type="button"
                            >
                              {rowPending &&
                              pendingAction === `reset-${target.id}` ? (
                                <LoaderCircle
                                  className="spin"
                                  aria-hidden="true"
                                  size={17}
                                />
                              ) : (
                                <KeyRound aria-hidden="true" size={17} />
                              )}
                            </button>
                          ) : null}

                          {canManageRow && !target.is_bot ? (
                            <>
                              <button
                                className="icon-button"
                                disabled={actionDisabled}
                                onClick={() => void handleMcpTokenReset(target)}
                                title={`重置 MCP 钥匙${target.mcp_token?.has_token ? `（当前 ${target.mcp_token.token_prefix}…）` : "（尚未生成）"}`}
                                aria-label="重置 MCP 钥匙"
                                type="button"
                              >
                                {pendingAction === `mcp-reset-${target.id}` ? (
                                  <LoaderCircle className="spin" aria-hidden="true" size={17} />
                                ) : (
                                  <Fingerprint aria-hidden="true" size={17} />
                                )}
                              </button>
                              <button
                                className={`icon-button${target.mcp_token?.status === "disabled" ? "" : ` ${styles.iconDanger}`}`}
                                disabled={actionDisabled}
                                onClick={() => void handleMcpTokenToggle(target)}
                                title={target.mcp_token?.status === "disabled" ? "启用 MCP 钥匙" : "停用 MCP 钥匙（他的 Codex 立刻连不上）"}
                                aria-label={target.mcp_token?.status === "disabled" ? "启用 MCP 钥匙" : "停用 MCP 钥匙"}
                                type="button"
                              >
                                {pendingAction === `mcp-toggle-${target.id}` ? (
                                  <LoaderCircle className="spin" aria-hidden="true" size={17} />
                                ) : target.mcp_token?.status === "disabled" ? (
                                  <ShieldCheck aria-hidden="true" size={17} />
                                ) : (
                                  <ShieldOff aria-hidden="true" size={17} />
                                )}
                              </button>
                            </>
                          ) : null}

                          {canManageRow &&
                          !target.is_active &&
                          isOwnerRole(currentUser?.role) ? (
                            <button
                              className={`icon-button ${styles.iconDanger}`}
                              disabled={isBusy}
                              onClick={() => void handlePurge(target)}
                              title="彻底删除（仅限已停用账号）"
                              aria-label="彻底删除"
                              type="button"
                            >
                              {pendingAction === `purge-${target.id}` ? (
                                <LoaderCircle
                                  className="spin"
                                  aria-hidden="true"
                                  size={17}
                                />
                              ) : (
                                <Trash2 aria-hidden="true" size={17} />
                              )}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                  })}
                </tbody>
              </table>
            </div>
            <div className="review-pager">
              <button
                className="secondary-button"
                disabled={isBusy || isLoading || userOffset === 0}
                onClick={() =>
                  void loadUsers(
                    true,
                    Math.max(0, userOffset - USERS_PAGE_LIMIT),
                  )
                }
                type="button"
              >
                上一页
              </button>
              <span>{Math.floor(userOffset / USERS_PAGE_LIMIT) + 1}</span>
              <button
                className="secondary-button"
                disabled={
                  isBusy ||
                  isLoading ||
                  userOffset + USERS_PAGE_LIMIT >= userCount
                }
                onClick={() =>
                  void loadUsers(true, userOffset + USERS_PAGE_LIMIT)
                }
                type="button"
              >
                下一页
              </button>
            </div>
          </>
        ) : null}
      </div>

      {expandedUser ? (
        <>
          <button
            aria-label="关闭详情"
            className="um-scrim on"
            onClick={() => setExpandedUser(null)}
            type="button"
          />
        <section className="user-detail-panel um-drawer on" aria-label="用户详情">
          <div className="users-panel-heading">
            <div>
              <span className="eyebrow">用户详情</span>
              <h3>{managedUserDisplayName(expandedUser)}</h3>
            </div>
            <button
              className="icon-button"
              onClick={() => setExpandedUser(null)}
              title="关闭详情"
              type="button"
            >
              <Eye aria-hidden="true" size={17} />
            </button>
          </div>

          <dl className="user-detail-grid">
            <div>
              <dt>用户名</dt>
              <dd>{expandedUser.username}</dd>
            </div>
            <div>
              <dt>角色</dt>
              <dd>
                {roleLabel(expandedUser.role)}
                <span className="user-detail-description">
                  {roleDescription(expandedUser.role)}
                </span>
              </dd>
            </div>
            {!isOwnerRole(expandedUser.role) ? (
              <>
                <div>
                  <dt>岗位</dt>
                  <dd>{expandedUser.job_title ?? "未设置"}</dd>
                </div>
                <div>
                  <dt>组织</dt>
                  <dd>
                    {expandedUser.organization_id
                      ? organizationById.get(expandedUser.organization_id)
                          ?.org_name ??
                        expandedUser.organization ??
                        expandedUser.organization_id
                      : "未设置"}
                  </dd>
                </div>
              </>
            ) : null}
            <div>
              <dt>状态</dt>
              <dd>{expandedUser.is_active ? "正常" : "已停用"}</dd>
            </div>
            <div>
              <dt>MCP 钥匙</dt>
              <dd>
                {expandedUser.is_bot
                  ? "机器人不发"
                  : !expandedUser.mcp_token?.has_token
                    ? "尚未生成"
                    : `${expandedUser.mcp_token.status === "disabled" ? "已停用" : "正常"} · ${expandedUser.mcp_token.token_prefix}…${
                        expandedUser.mcp_token.last_used_at
                          ? ` · 上次使用 ${new Date(expandedUser.mcp_token.last_used_at).toLocaleString("zh-CN")}`
                          : ""
                      }`}
              </dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{formatDate(expandedUser.created_at)}</dd>
            </div>
            <div>
              <dt>更新时间</dt>
              <dd>{formatDate(expandedUser.updated_at)}</dd>
            </div>
            <div>
              <dt>最近登录</dt>
              <dd>{formatDate(expandedUser.last_login_at)}</dd>
            </div>
          </dl>

          {isManagedUserRole(expandedUser.role) && canManageTarget(expandedUser) ? (
            <form className="users-role-form" onSubmit={handleRoleUpdate}>
              <label className="field-group">
                <span>角色</span>
                <select
                  className="select-shell"
                  disabled={
                    isBusy ||
                    isRoleCatalogLoading ||
                    assignableRoleOptions.length === 0 ||
                    expandedUser.id === currentUser?.id
                  }
                  onChange={(event) =>
                    setDetailRole(event.target.value as ManagedUserRole)
                  }
                  value={detailRole}
                >
                  {assignableRoleOptions.map((role) => (
                    <option key={role.name} value={role.name}>
                      {roleLabel(role.name)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="secondary-button"
                disabled={
                  isBusy ||
                  isRoleCatalogLoading ||
                  assignableRoleOptions.length === 0 ||
                  expandedUser.id === currentUser?.id ||
                  detailRole === expandedUser.role
                }
                type="submit"
              >
                <Save aria-hidden="true" size={17} />
                保存角色
              </button>
            </form>
          ) : (
            <p className="users-muted-note">
              当前账号仅可查看该用户详情。
            </p>
          )}
        </section>
        </>
      ) : null}
    </section>
  );
}
