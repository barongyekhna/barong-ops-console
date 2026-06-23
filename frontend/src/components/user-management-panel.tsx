"use client";

import {
  Eye,
  KeyRound,
  LoaderCircle,
  Plus,
  Power,
  PowerOff,
  RotateCcw,
  Save,
  ShieldAlert,
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
import {
  MANAGED_USER_ROLES,
  USERS_PAGE_LIMIT,
  createUser,
  disableUser,
  enableUser,
  formatUsersApiError,
  getUser,
  isManagedUserRole,
  listOrganizations,
  listUserRoles,
  listUsers,
  resetUserPassword,
  updateUser,
  type ManagedUser,
  type ManagedUserRole,
  type OrganizationOption,
  type UserRoleMetadata,
  type UserRolesResponse,
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

function canManageUsers(role: string | undefined) {
  return role === "owner" || role === "super_admin";
}

function isOwnerRole(role: string) {
  return role === "owner";
}

function roleLabel(role: string) {
  const labels: Record<string, string> = {
    operator: "操作员",
    owner: "owner",
    reviewer: "审核员",
    super_admin: "组织管理员",
    viewer: "查看员",
  };
  return labels[role] ?? "成员";
}

function roleDescription(role: string) {
  const descriptions: Record<string, string> = {
    operator: "处理已授权的业务操作。",
    owner: "拥有全部权限。",
    reviewer: "审核已授权的业务。",
    super_admin: "管理所属组织内的账号和功能。",
    viewer: "查看已授权的内容。",
  };
  return descriptions[role] ?? "按授权范围访问工作台。";
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
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [expandedUser, setExpandedUser] = useState<ManagedUser | null>(null);
  const [detailRole, setDetailRole] =
    useState<ManagedUserRole>("viewer");
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [createUsername, setCreateUsername] = useState("");
  const [createJobTitle, setCreateJobTitle] = useState("");
  const [createOrganizationId, setCreateOrganizationId] = useState("");
  const [createRole, setCreateRole] =
    useState<ManagedUserRole>("viewer");

  const userCanManageUsers = canManageUsers(currentUser?.role);
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
    if (!userCanManageUsers) {
      setOrganizations([]);
      setOrganizationsError("");
      setIsOrganizationsLoading(false);
      return;
    }

    setIsOrganizationsLoading(true);
    setOrganizationsError("");
    try {
      const result = await listOrganizations();
      setOrganizations(result.items);
    } catch (error) {
      setOrganizationsError(
        formatUsersApiError(
          error,
          "组织数据暂未同步，请重试。",
        ),
      );
    } finally {
      setIsOrganizationsLoading(false);
    }
  }, [userCanManageUsers]);

  const loadUsers = useCallback(
    async (showLoading = true, offset = userOffset) => {
      if (!userCanManageUsers) {
        setIsLoading(false);
        return;
      }

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
    [userCanManageUsers, userOffset],
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

  const assignableRoleOptions = useMemo(() => {
    if (!roleCatalog) {
      return roleCatalogError ? FALLBACK_ASSIGNABLE_ROLES : [];
    }

    return roleCatalog.assignable_roles.filter(
      (role) => role.assignable && isManagedUserRole(role.name),
    );
  }, [roleCatalog, roleCatalogError]);

  const assignableRoleNames = useMemo(
    () => new Set(assignableRoleOptions.map((role) => role.name)),
    [assignableRoleOptions],
  );

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
      organizations.length > 0 &&
      !createOrganizationId &&
      !isOwnerRole(createRole)
    ) {
      setCreateOrganizationId(organizations[0].org_id);
    }
  }, [createOrganizationId, createRole, organizations]);

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
      setCreateUsername("");
      setCreateJobTitle("");
      setCreateOrganizationId(
        organizations.length > 0 ? organizations[0].org_id : "",
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
    if (target.id === currentUser?.id) {
      setActionError("不能在这里停用当前登录账号。");
      return;
    }
    if (
      !window.confirm(
        `确认停用 ${target.username}？停用后该账号将无法登录。`,
      )
    ) {
      return;
    }

    setPendingAction(`disable-${target.id}`);
    try {
      const updated = await disableUser(target.id);
      setActionNotice(`已停用账号：${updated.username}。`);
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
    if (!window.confirm(`确认启用 ${target.username}？`)) {
      return;
    }

    setPendingAction(`enable-${target.id}`);
    try {
      const updated = await enableUser(target.id);
      setActionNotice(`已启用账号：${updated.username}。`);
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
      setActionNotice(`已更新 ${updated.username} 的角色。`);
      await refreshAfterMutation(expandedUser.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "角色更新未完成，请重试。"),
      );
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
        `确认重置 ${resetTarget.username} 的密码？原密码将立即失效。`,
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
      setActionNotice(`已重置 ${updated.username} 的密码。`);
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

  if (!userCanManageUsers) {
    return (
      <section className="list-state list-error" role="alert">
        <div>
          <h2>无权管理用户</h2>
          <p>
            仅owner和组织管理员可以管理工作台账号。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="users-workspace" aria-label="用户管理">
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
                organizations.length === 0
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
              ) : organizations.length === 0 ? (
                <option value="">暂无可选组织</option>
              ) : (
                organizations.map((organization) => (
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
            (!isOwnerRole(createRole) && organizations.length === 0)
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

      {resetTarget ? (
        <form className="users-reset-panel" onSubmit={handleReset}>
          <div>
            <span className="eyebrow">密码重置</span>
            <h3>{resetTarget.username}</h3>
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
              className="danger-button"
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
      ) : null}

      <div className="users-list-panel">
        <div className="users-list-heading">
          <div>
            <h3>用户列表</h3>
            <p>共 {userCount} 个账号，每页 {USERS_PAGE_LIMIT} 条。</p>
          </div>
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
                  const actionDisabled = isBusy || isSelf;
                  const rowPending =
                    pendingAction?.endsWith(`-${target.id}`) ?? false;
                  const targetOrganization = target.organization_id
                    ? organizationById.get(target.organization_id)
                    : null;
                  const showOrgFields = !isOwnerRole(target.role);

                  return (
                    <tr key={target.id}>
                      <td>
                        <strong>{target.username}</strong>
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
                          ? targetOrganization?.org_name ??
                            (target.organization_id ? "未匹配组织" : "")
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

                          {target.is_active ? (
                            <button
                              className="secondary-button"
                              disabled={actionDisabled}
                              onClick={() => void handleDisable(target)}
                              title={
                                isSelf
                                  ? "不能停用当前账号"
                                  : "停用用户"
                              }
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
                              停用
                            </button>
                          ) : (
                            <button
                              className="secondary-button"
                              disabled={isBusy}
                              onClick={() => void handleEnable(target)}
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
                              启用
                            </button>
                          )}

                          <button
                            className="danger-button"
                            disabled={actionDisabled}
                            onClick={() => {
                              clearActionMessages();
                              setResetTarget(target);
                              setResetPassword("");
                            }}
                            title={
                              isSelf
                                ? "不能重置当前账号密码"
                                : "重置密码"
                            }
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
                            重置
                          </button>
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
        <section className="user-detail-panel" aria-label="用户详情">
          <div className="users-panel-heading">
            <div>
              <span className="eyebrow">用户详情</span>
              <h3>{expandedUser.username}</h3>
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
                          ?.org_name ?? "未匹配组织"
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

          {isManagedUserRole(expandedUser.role) ? (
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
              owner和保留角色仅用于查看，不能在这里修改。
            </p>
          )}
        </section>
      ) : null}
    </section>
  );
}
