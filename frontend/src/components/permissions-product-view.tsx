"use client";

import {
  CheckCircle2,
  ChevronDown,
  KeyRound,
  LoaderCircle,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  Undo2,
  Users,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { DashboardScene } from "@/components/dashboard-scene";
import {
  HIGH_RISK_CONFIRMATION_TEXT,
  PERMISSION_TREE_SCOPE_KEY,
  PERMISSION_TREE_SCOPE_TYPE,
  assignedPermissionMap,
  buildPermissionTree,
  canManagePermissionAssignments,
  canViewPermissionCenter,
  computeAssignmentDiff,
  detectHighRiskPermission,
  formatPermissionAssignmentsApiError,
  getPermissionCategoryLabel,
  getPermissionUiCategory,
  grantUserPermissionAssignment,
  hasBuiltinFullFeatureAccess,
  listPermissionRegistry,
  listUserPermissionAssignments,
  moduleCheckState,
  revokeUserPermissionAssignment,
  splitPermissionDisplayName,
  updateUserPermissionAssignment,
  type PermissionAssignment,
  type PermissionCheckState,
  type PermissionRegistryItem,
  type PermissionTreeModule,
} from "@/lib/permission-management-api";
import {
  formatUsersApiError,
  listUsers,
  managedUserDisplayName,
  type ManagedUser,
} from "@/lib/users-api";
import { isOwnerRole, isSuperAdminRole, normalizeRole } from "@/lib/roles";

const ASSIGNMENT_REASON = "Permission center assignment update.";
const GLOBAL_SCOPE_TYPE = PERMISSION_TREE_SCOPE_TYPE;
const GLOBAL_SCOPE_KEY = PERMISSION_TREE_SCOPE_KEY;
const UNSAVED_PROMPT = "当前员工有未保存的权限改动，放弃这些改动吗？";

type ViewTab = "user" | "permission";

type SaveFailure = {
  key: string;
  label: string;
  message: string;
};

function roleLabel(role: string) {
  if (isOwnerRole(role)) {
    return "owner";
  }
  if (isSuperAdminRole(role)) {
    return "组织管理员";
  }
  return "普通用户";
}

function riskLabel(permission: PermissionRegistryItem) {
  return detectHighRiskPermission(permission) ? "高风险" : "常规";
}

function permissionAssignmentForUser(
  assignments: PermissionAssignment[],
  permissionKey: string,
) {
  return (
    assignments.find(
      (assignment) =>
        assignment.permission_key === permissionKey &&
        assignment.scope_type === GLOBAL_SCOPE_TYPE &&
        assignment.scope_key === GLOBAL_SCOPE_KEY,
    ) ??
    assignments.find((assignment) => assignment.permission_key === permissionKey) ??
    null
  );
}

function userSearchText(user: ManagedUser) {
  return [
    user.username,
    user.display_name ?? "",
    user.nickname ?? "",
    user.job_title ?? "",
    user.organization_id ?? "",
    user.role,
  ]
    .join(" ")
    .toLowerCase();
}

function highRiskConfirmation(permission: PermissionRegistryItem) {
  return detectHighRiskPermission(permission)
    ? {
        confirm_high_risk: true,
        confirmation_text: HIGH_RISK_CONFIRMATION_TEXT,
      }
    : {};
}

/** 三态复选框：模块行 / 全选行用。indeterminate 只能靠 DOM 属性设。 */
function TriCheckbox({
  ariaLabel,
  disabled,
  onChange,
  state,
}: {
  ariaLabel: string;
  disabled?: boolean;
  onChange: () => void;
  state: PermissionCheckState;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = state === "some";
    }
  }, [state]);
  return (
    <input
      aria-label={ariaLabel}
      checked={state === "all"}
      disabled={disabled}
      onChange={onChange}
      ref={ref}
      type="checkbox"
    />
  );
}

function PermissionCard({
  disabled,
  onClick,
  permission,
}: {
  disabled?: boolean;
  onClick?: () => void;
  permission: PermissionRegistryItem;
}) {
  const name = splitPermissionDisplayName(permission);
  const content = (
    <>
      <span className="permissions-card-kicker">
        {getPermissionCategoryLabel(getPermissionUiCategory(permission))}
      </span>
      <strong>{name.label}</strong>
      <small className="pm-key">{name.key}</small>
      <span
        className={
          detectHighRiskPermission(permission)
            ? "permissions-risk-badge permissions-risk-high"
            : "permissions-risk-badge"
        }
      >
        {riskLabel(permission)}
      </span>
    </>
  );

  if (!onClick) {
    return <article className="permissions-card">{content}</article>;
  }

  return (
    <button
      className="permissions-card permissions-card-button"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {content}
    </button>
  );
}

export function PermissionsProductView() {
  const { status, user } = useAuth();
  const role = normalizeRole(user?.role);
  const canViewControlPlanePermissions = isOwnerRole(role);
  const canView = status === "authenticated" && canViewPermissionCenter(role);
  const canWriteAssignments = canManagePermissionAssignments(role);

  const [activeTab, setActiveTab] = useState<ViewTab>("user");
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [registry, setRegistry] = useState<PermissionRegistryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  // ---- 按员工授权 ----
  const [userSearch, setUserSearch] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<PermissionAssignment[]>([]);
  const [draft, setDraft] = useState<Set<string>>(() => new Set());
  const [isAssignmentsLoading, setIsAssignmentsLoading] = useState(false);
  const [assignmentsError, setAssignmentsError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveProgress, setSaveProgress] = useState({ done: 0, total: 0 });
  const [saveNotice, setSaveNotice] = useState("");
  const [saveFailures, setSaveFailures] = useState<SaveFailure[]>([]);
  const [collapsedModules, setCollapsedModules] = useState<Set<string>>(
    () => new Set(),
  );

  // ---- 按权限查看（保留原有弹窗） ----
  const [selectedPermission, setSelectedPermission] =
    useState<PermissionRegistryItem | null>(null);
  const [dialogAssignments, setDialogAssignments] = useState<
    Record<number, PermissionAssignment | null>
  >({});
  const [dialogSearchQuery, setDialogSearchQuery] = useState("");
  const [isDialogLoading, setIsDialogLoading] = useState(false);
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [dialogError, setDialogError] = useState("");
  const [dialogNotice, setDialogNotice] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    () => new Set(),
  );

  const toggleInSet = (
    setter: (updater: (prev: Set<string>) => Set<string>) => void,
    id: string,
  ) => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };
  const toggleGroup = useCallback(
    (id: string) => toggleInSet(setCollapsedGroups, id),
    [],
  );
  const toggleModule = useCallback(
    (id: string) => toggleInSet(setCollapsedModules, id),
    [],
  );

  const tree = useMemo(
    () => buildPermissionTree(registry, role),
    [registry, role],
  );
  const grantableModules = useMemo(
    () => tree.filter((moduleNode) => moduleNode.grantable),
    [tree],
  );
  const controlPlaneModule = useMemo(
    () => tree.find((moduleNode) => !moduleNode.grantable) ?? null,
    [tree],
  );
  const grantableKeys = useMemo(
    () =>
      grantableModules.flatMap((moduleNode) =>
        moduleNode.permissions.map((permission) => permission.permission_key),
      ),
    [grantableModules],
  );
  const featurePermissionCount = grantableKeys.length;
  const controlPlaneCount = controlPlaneModule?.permissions.length ?? 0;

  const assignableUsers = useMemo(
    () =>
      users.filter((targetUser) => {
        if (isOwnerRole(targetUser.role)) {
          return false;
        }
        if (isSuperAdminRole(role)) {
          return (
            targetUser.organization_id === user?.organization_id &&
            !isSuperAdminRole(targetUser.role)
          );
        }
        return true;
      }),
    [role, user?.organization_id, users],
  );
  const filteredUsers = useMemo(() => {
    const query = userSearch.trim().toLowerCase();
    if (!query) {
      return assignableUsers;
    }
    return assignableUsers.filter((targetUser) =>
      userSearchText(targetUser).includes(query),
    );
  }, [assignableUsers, userSearch]);
  const filteredDialogUsers = useMemo(() => {
    const query = dialogSearchQuery.trim().toLowerCase();
    if (!query) {
      return assignableUsers;
    }
    return assignableUsers.filter((targetUser) =>
      userSearchText(targetUser).includes(query),
    );
  }, [assignableUsers, dialogSearchQuery]);
  const selectedUser = useMemo(
    () =>
      assignableUsers.find((targetUser) => targetUser.id === selectedUserId) ??
      null,
    [assignableUsers, selectedUserId],
  );

  const currentMap = useMemo(
    () => assignedPermissionMap(assignments),
    [assignments],
  );
  const diff = useMemo(
    () => computeAssignmentDiff(currentMap, draft, tree),
    [currentMap, draft, tree],
  );
  const isDirty = diff.grants.length > 0 || diff.revokes.length > 0;
  const allState = moduleCheckState(grantableKeys, draft);
  const liveGrantableCount = grantableKeys.filter((key) =>
    currentMap.has(key),
  ).length;

  const load = useCallback(async () => {
    if (!canView) {
      setUsers([]);
      setRegistry([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError("");
    const loadErrors: string[] = [];
    try {
      const userResult = await listUsers(100);
      setUsers(userResult.items);
    } catch (loadError) {
      loadErrors.push(
        formatUsersApiError(loadError, "用户数据暂未同步，请重试。"),
      );
    }

    try {
      const registryResult = await listPermissionRegistry();
      setRegistry(registryResult);
    } catch (loadError) {
      loadErrors.push(
        formatUsersApiError(loadError, "权限数据暂未同步，请重试。"),
      );
    }

    if (loadErrors.length > 0) {
      setError(loadErrors.join(" "));
    }
    setIsLoading(false);
  }, [canView]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 拉一次该员工的授权，草稿重置为线上状态。 */
  const loadUserAssignments = useCallback(
    async (userId: number) => {
      setIsAssignmentsLoading(true);
      setAssignmentsError("");
      try {
        const response = await listUserPermissionAssignments(userId);
        const liveMap = assignedPermissionMap(response.assignments);
        setAssignments(response.assignments);
        setDraft(
          new Set(grantableKeys.filter((key) => liveMap.has(key))),
        );
      } catch (loadError) {
        setAssignments([]);
        setDraft(new Set());
        setAssignmentsError(
          formatPermissionAssignmentsApiError(
            loadError,
            "该员工的权限暂未同步，请重试。",
          ),
        );
      } finally {
        setIsAssignmentsLoading(false);
      }
    },
    [grantableKeys],
  );

  // 注册表晚于员工到达时，草稿里的 key 集合要按注册表重算一次。
  useEffect(() => {
    if (selectedUserId !== null && assignments.length > 0 && !isDirty) {
      const liveMap = assignedPermissionMap(assignments);
      setDraft(new Set(grantableKeys.filter((key) => liveMap.has(key))));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grantableKeys]);

  function selectUser(targetUser: ManagedUser) {
    if (targetUser.id === selectedUserId) {
      return;
    }
    if (isDirty && !window.confirm(UNSAVED_PROMPT)) {
      return;
    }
    setSelectedUserId(targetUser.id);
    setSaveNotice("");
    setSaveFailures([]);
    void loadUserAssignments(targetUser.id);
  }

  function switchTab(tab: ViewTab) {
    if (tab === activeTab) {
      return;
    }
    if (activeTab === "user" && isDirty && !window.confirm(UNSAVED_PROMPT)) {
      return;
    }
    setActiveTab(tab);
    // 从「按权限查看」回来时，那边可能改过这个人的授权，重拉一次。
    if (tab === "user" && selectedUserId !== null) {
      setSaveNotice("");
      setSaveFailures([]);
      void loadUserAssignments(selectedUserId);
    }
  }

  function toggleLeaf(key: string) {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleModuleAll(moduleNode: PermissionTreeModule) {
    const keys = moduleNode.permissions.map((p) => p.permission_key);
    const state = moduleCheckState(keys, draft);
    setDraft((prev) => {
      const next = new Set(prev);
      if (state === "all") {
        for (const key of keys) {
          next.delete(key);
        }
      } else {
        for (const key of keys) {
          next.add(key);
        }
      }
      return next;
    });
  }

  function toggleEverything() {
    setDraft(allState === "all" ? new Set() : new Set(grantableKeys));
  }

  function discardDraft() {
    setDraft(new Set(grantableKeys.filter((key) => currentMap.has(key))));
    setSaveNotice("");
    setSaveFailures([]);
  }

  async function saveDraft() {
    if (!selectedUser || !canWriteAssignments || !isDirty || isSaving) {
      return;
    }
    if (diff.highRiskGrants.length > 0) {
      const names = diff.highRiskGrants
        .map((permission) => {
          const name = splitPermissionDisplayName(permission);
          return `· ${name.label}（${name.key}）`;
        })
        .join("\n");
      if (
        !window.confirm(
          `以下 ${diff.highRiskGrants.length} 项为高风险权限，确认授予 ${managedUserDisplayName(selectedUser)}？\n\n${names}`,
        )
      ) {
        return;
      }
    }

    setIsSaving(true);
    setSaveNotice("");
    setSaveFailures([]);
    const total = diff.grants.length + diff.revokes.length;
    setSaveProgress({ done: 0, total });
    const failures: SaveFailure[] = [];
    let done = 0;
    let granted = 0;
    let revoked = 0;

    for (const permission of diff.grants) {
      try {
        await grantUserPermissionAssignment(selectedUser.id, {
          permission_key: permission.permission_key,
          reason: ASSIGNMENT_REASON,
          scope_key: GLOBAL_SCOPE_KEY,
          scope_type: GLOBAL_SCOPE_TYPE,
          ...highRiskConfirmation(permission),
        });
        granted += 1;
      } catch (saveError) {
        const name = splitPermissionDisplayName(permission);
        failures.push({
          key: name.key,
          label: name.label,
          message: formatPermissionAssignmentsApiError(saveError, "授权失败。"),
        });
      }
      done += 1;
      setSaveProgress({ done, total });
    }

    for (const entry of diff.revokes) {
      try {
        await revokeUserPermissionAssignment(
          selectedUser.id,
          entry.assignment.id,
          { reason: ASSIGNMENT_REASON },
        );
        revoked += 1;
      } catch (saveError) {
        const name = splitPermissionDisplayName(entry.permission);
        failures.push({
          key: name.key,
          label: name.label,
          message: formatPermissionAssignmentsApiError(saveError, "撤销失败。"),
        });
      }
      done += 1;
      setSaveProgress({ done, total });
    }

    // 以线上回读为准，不信任本地计数。
    await loadUserAssignments(selectedUser.id);
    setSaveFailures(failures);
    setSaveNotice(
      failures.length === 0
        ? `已保存：新增 ${granted} 项，撤销 ${revoked} 项。`
        : `已保存 ${granted + revoked} 项，${failures.length} 项失败，树已按线上状态刷新。`,
    );
    setIsSaving(false);
  }

  // ---- 按权限查看：沿用原有逻辑 ----
  const loadDialogAssignments = useCallback(
    async (permission: PermissionRegistryItem, targetUsers: ManagedUser[]) => {
      if (!canWriteAssignments) {
        setDialogAssignments({});
        setIsDialogLoading(false);
        return;
      }

      setIsDialogLoading(true);
      setDialogError("");
      setDialogNotice("");
      const rows: Record<number, PermissionAssignment | null> = {};
      let failedCount = 0;
      for (const targetUser of targetUsers) {
        try {
          const response = await listUserPermissionAssignments(targetUser.id);
          rows[targetUser.id] = permissionAssignmentForUser(
            response.assignments,
            permission.permission_key,
          );
        } catch {
          failedCount += 1;
        }
      }
      setDialogAssignments((current) => ({ ...current, ...rows }));
      if (failedCount > 0) {
        setDialogError("部分员工权限暂未同步，已显示可用员工。");
      }
      setIsDialogLoading(false);
    },
    [canWriteAssignments],
  );

  function openPermissionDialog(permission: PermissionRegistryItem) {
    setSelectedPermission(permission);
    setDialogSearchQuery("");
    setDialogAssignments({});
    setDialogError("");
    setDialogNotice("");
    void loadDialogAssignments(permission, assignableUsers);
  }

  async function refreshUserAssignment(
    targetUser: ManagedUser,
    permission: PermissionRegistryItem,
  ) {
    const response = await listUserPermissionAssignments(targetUser.id);
    const assignment = permissionAssignmentForUser(
      response.assignments,
      permission.permission_key,
    );
    setDialogAssignments((current) => ({
      ...current,
      [targetUser.id]: assignment,
    }));
  }

  async function handleUserPermissionToggle(
    targetUser: ManagedUser,
    checked: boolean,
  ) {
    if (!selectedPermission || !canWriteAssignments) {
      return;
    }

    setPendingUserId(targetUser.id);
    setDialogError("");
    setDialogNotice("");
    const confirmation = highRiskConfirmation(selectedPermission);
    const assignment = dialogAssignments[targetUser.id] ?? null;

    try {
      if (checked) {
        if (assignment?.id) {
          await updateUserPermissionAssignment(targetUser.id, assignment.id, {
            enabled: true,
            reason: ASSIGNMENT_REASON,
            ...confirmation,
          });
        } else {
          await grantUserPermissionAssignment(targetUser.id, {
            permission_key: selectedPermission.permission_key,
            reason: ASSIGNMENT_REASON,
            scope_key: GLOBAL_SCOPE_KEY,
            scope_type: GLOBAL_SCOPE_TYPE,
            ...confirmation,
          });
        }
      } else if (assignment?.id) {
        await revokeUserPermissionAssignment(targetUser.id, assignment.id, {
          reason: ASSIGNMENT_REASON,
        });
      }

      await refreshUserAssignment(targetUser, selectedPermission);
      setDialogNotice("权限已更新。");
    } catch (actionError) {
      setDialogError(
        formatPermissionAssignmentsApiError(actionError, "操作未完成，请重试。"),
      );
    } finally {
      setPendingUserId(null);
    }
  }

  if (!canView) {
    return null;
  }

  const hasData = registry.length > 0 || users.length > 0;
  // 组织管理员作为目标：本组织全部功能权限内置，树整棵打勾但锁死，不走保存。
  const targetHasBuiltinAccess =
    selectedUser !== null && hasBuiltinFullFeatureAccess(selectedUser.role);
  const treeDisabled =
    !canWriteAssignments ||
    isAssignmentsLoading ||
    isSaving ||
    !selectedUser ||
    targetHasBuiltinAccess;
  const isChecked = (key: string) => targetHasBuiltinAccess || draft.has(key);
  const displayAllState = targetHasBuiltinAccess ? "all" : allState;

  return (
    <section className="product-console mm-page pm-page" aria-label="权限管理">
      <DashboardScene />
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">账号与组织</span>
          <h2>权限管理</h2>
          <p>先选员工，再按模块整棵勾选；改动只在点「保存」时写入。</p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => {
            if (isDirty && !window.confirm(UNSAVED_PROMPT)) {
              return;
            }
            void load();
            if (selectedUserId !== null) {
              void loadUserAssignments(selectedUserId);
            }
          }}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          {isLoading ? "同步中" : "刷新"}
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>员工</span>
          <strong>{users.length}</strong>
        </div>
        <div>
          <span>功能权限</span>
          <strong>{featurePermissionCount}</strong>
        </div>
        {canViewControlPlanePermissions ? (
          <div>
            <span>系统权限</span>
            <strong>{controlPlaneCount}</strong>
          </div>
        ) : null}
        <div>
          <span>当前角色</span>
          <strong>{roleLabel(role)}</strong>
        </div>
      </div>

      <div className="mm-tabs" role="tablist">
        <button
          aria-selected={activeTab === "user"}
          className={`mm-tab ${activeTab === "user" ? "on" : ""}`}
          onClick={() => switchTab("user")}
          role="tab"
          type="button"
        >
          <Users aria-hidden="true" size={15} />
          按员工授权 <span className="mm-n">{assignableUsers.length}</span>
        </button>
        <button
          aria-selected={activeTab === "permission"}
          className={`mm-tab ${activeTab === "permission" ? "on" : ""}`}
          onClick={() => switchTab("permission")}
          role="tab"
          type="button"
        >
          <KeyRound aria-hidden="true" size={15} />
          按权限查看 <span className="mm-n">{featurePermissionCount}</span>
        </button>
      </div>

      {isLoading && !hasData ? (
        <section className="list-state">
          <div className="skeleton-stack" aria-hidden="true">
            <span className="skeleton-line medium" />
            <span className="skeleton-line" />
            <span className="skeleton-line short" />
          </div>
        </section>
      ) : null}

      {error ? (
        <section className="list-state list-error" role="alert">
          <div>
            <h2>{hasData ? "部分数据暂未同步" : "权限数据暂未同步"}</h2>
            <p>{error}</p>
            {hasData ? <p>正在显示上一次成功加载的数据。</p> : null}
          </div>
          <button
            className="primary-button"
            onClick={() => void load()}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
            重试
          </button>
        </section>
      ) : null}

      {hasData && activeTab === "user" ? (
        <div className="pm-split">
          <aside className="ops-panel pm-users" aria-label="员工">
            <div className="ops-panel-heading">
              <div>
                <h3>员工</h3>
                <p>选一个人，右侧显示 TA 的权限树。</p>
              </div>
            </div>
            <label className="field-group pm-user-search">
              <span className="input-shell">
                <Search aria-hidden="true" size={16} />
                <input
                  onChange={(event) => setUserSearch(event.target.value)}
                  placeholder="搜索用户名 / 职位 / 组织"
                  type="search"
                  value={userSearch}
                />
              </span>
            </label>
            <div className="pm-user-list">
              {filteredUsers.map((targetUser) => (
                <button
                  className={`pm-user-row${
                    targetUser.id === selectedUserId ? " on" : ""
                  }`}
                  key={targetUser.id}
                  onClick={() => selectUser(targetUser)}
                  type="button"
                >
                  <strong>{managedUserDisplayName(targetUser)}</strong>
                  <small>
                    {[
                      managedUserDisplayName(targetUser) !== targetUser.username
                        ? targetUser.username
                        : null,
                      targetUser.job_title,
                      targetUser.organization,
                    ]
                      .filter(Boolean)
                      .join(" / ") || roleLabel(targetUser.role)}
                  </small>
                </button>
              ))}
              {filteredUsers.length === 0 ? (
                <div className="ops-empty-state">
                  <strong>暂无员工</strong>
                  <span>请更换搜索条件。</span>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="ops-panel pm-tree-panel" aria-label="权限树">
            {!selectedUser ? (
              <div className="ops-empty-state pm-tree-empty">
                <strong>还没选员工</strong>
                <span>在左侧点一个人，这里会显示可勾选的权限树。</span>
              </div>
            ) : (
              <>
                <div className="ops-panel-heading">
                  <div>
                    <h3>{managedUserDisplayName(selectedUser)}</h3>
                    <p>
                      {managedUserDisplayName(selectedUser) !== selectedUser.username
                        ? `${selectedUser.username} · `
                        : ""}
                      {roleLabel(selectedUser.role)}
                      {selectedUser.job_title ? ` · ${selectedUser.job_title}` : ""}
                      {selectedUser.organization
                        ? ` · ${selectedUser.organization}`
                        : ""}
                    </p>
                  </div>
                  <div className="pm-head-tools">
                    <span className="ops-source">
                      {targetHasBuiltinAccess
                        ? `内置 ${featurePermissionCount} / ${featurePermissionCount}`
                        : `线上 ${liveGrantableCount} / ${featurePermissionCount}`}
                    </span>
                  </div>
                </div>

                {!canWriteAssignments ? (
                  <div className="users-alert users-alert-error" role="note">
                    <ShieldAlert aria-hidden="true" size={18} />
                    <span>当前角色不能修改授权，这里是只读视图。</span>
                  </div>
                ) : null}

                {targetHasBuiltinAccess ? (
                  <div className="users-alert users-alert-success" role="note">
                    <ShieldCheck aria-hidden="true" size={18} />
                    <span>
                      组织管理员对本组织拥有全部功能权限（内置），不需要也不能单独授权；只有
                      owner 能调整管理员的角色。
                    </span>
                  </div>
                ) : null}

                {assignmentsError ? (
                  <div className="users-alert users-alert-error" role="alert">
                    <ShieldAlert aria-hidden="true" size={18} />
                    <span>{assignmentsError}</span>
                  </div>
                ) : null}

                {saveNotice ? (
                  <div
                    className={`users-alert ${
                      saveFailures.length > 0
                        ? "users-alert-error"
                        : "users-alert-success"
                    }`}
                    role="status"
                  >
                    {saveFailures.length > 0 ? (
                      <ShieldAlert aria-hidden="true" size={18} />
                    ) : (
                      <CheckCircle2 aria-hidden="true" size={18} />
                    )}
                    <span>{saveNotice}</span>
                  </div>
                ) : null}

                {saveFailures.length > 0 ? (
                  <ul className="pm-save-failures">
                    {saveFailures.map((failure) => (
                      <li key={failure.key}>
                        <strong>{failure.label}</strong>
                        <code className="pm-key">{failure.key}</code>
                        <span>{failure.message}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {isAssignmentsLoading ? (
                  <div className="list-state permissions-empty">
                    <LoaderCircle className="spin" aria-hidden="true" size={22} />
                    正在读取该员工的权限
                  </div>
                ) : (
                  <div className="pm-tree">
                    <label className="pm-tree-row pm-tree-all">
                      <TriCheckbox
                        ariaLabel="全选全部功能权限"
                        disabled={treeDisabled}
                        onChange={toggleEverything}
                        state={displayAllState}
                      />
                      <span className="pm-tree-label">
                        <strong>全选</strong>
                        <small>
                          已勾 {targetHasBuiltinAccess ? featurePermissionCount : draft.size} /{" "}
                          {featurePermissionCount}
                        </small>
                      </span>
                    </label>

                    {grantableModules.map((moduleNode) => {
                      const keys = moduleNode.permissions.map(
                        (p) => p.permission_key,
                      );
                      const state = targetHasBuiltinAccess
                        ? "all"
                        : moduleCheckState(keys, draft);
                      const checkedCount = keys.filter(isChecked).length;
                      const collapsed = collapsedModules.has(moduleNode.moduleKey);
                      return (
                        <div
                          className={`pm-tree-module${collapsed ? " collapsed" : ""}`}
                          key={moduleNode.moduleKey}
                        >
                          <div className="pm-tree-row pm-tree-module-row">
                            <TriCheckbox
                              ariaLabel={`全选 ${moduleNode.title}`}
                              disabled={treeDisabled}
                              onChange={() => toggleModuleAll(moduleNode)}
                              state={state}
                            />
                            <button
                              className="pm-tree-label pm-tree-toggle"
                              onClick={() => toggleModule(moduleNode.moduleKey)}
                              type="button"
                            >
                              <strong>{moduleNode.title}</strong>
                              <small>
                                {checkedCount} / {keys.length}
                              </small>
                              <ChevronDown aria-hidden="true" size={15} />
                            </button>
                          </div>
                          {!collapsed ? (
                            <div className="pm-tree-leaves">
                              {moduleNode.permissions.map((permission) => {
                                const name = splitPermissionDisplayName(permission);
                                const key = permission.permission_key;
                                const live = targetHasBuiltinAccess || currentMap.has(key);
                                const wanted = isChecked(key);
                                const changed = live !== wanted;
                                return (
                                  <label
                                    className={`pm-tree-row pm-tree-leaf${
                                      changed ? " changed" : ""
                                    }`}
                                    key={key}
                                  >
                                    <input
                                      checked={wanted}
                                      disabled={treeDisabled}
                                      onChange={() => toggleLeaf(key)}
                                      type="checkbox"
                                    />
                                    <span className="pm-tree-label">
                                      <strong>{name.label}</strong>
                                      <code className="pm-key">{name.key}</code>
                                    </span>
                                    {changed ? (
                                      <span className="pm-change-tag">
                                        {wanted ? "待新增" : "待撤销"}
                                      </span>
                                    ) : null}
                                    <span
                                      className={
                                        detectHighRiskPermission(permission)
                                          ? "permissions-risk-badge permissions-risk-high"
                                          : "permissions-risk-badge"
                                      }
                                    >
                                      {riskLabel(permission)}
                                    </span>
                                  </label>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}

                    {controlPlaneModule ? (
                      <div
                        className={`pm-tree-module pm-tree-readonly${
                          collapsedModules.has(controlPlaneModule.moduleKey)
                            ? " collapsed"
                            : ""
                        }`}
                      >
                        <div className="pm-tree-row pm-tree-module-row">
                          <input aria-label="系统权限不可授权" disabled type="checkbox" />
                          <button
                            className="pm-tree-label pm-tree-toggle"
                            onClick={() => toggleModule(controlPlaneModule.moduleKey)}
                            type="button"
                          >
                            <strong>{controlPlaneModule.title}</strong>
                            <small>{controlPlaneModule.permissions.length} 项 · owner 专属</small>
                            <ChevronDown aria-hidden="true" size={15} />
                          </button>
                        </div>
                        {!collapsedModules.has(controlPlaneModule.moduleKey) ? (
                          <div className="pm-tree-leaves">
                            {controlPlaneModule.permissions.map((permission) => {
                              const name = splitPermissionDisplayName(permission);
                              return (
                                <div
                                  className="pm-tree-row pm-tree-leaf"
                                  key={permission.permission_key}
                                >
                                  <input disabled type="checkbox" />
                                  <span className="pm-tree-label">
                                    <strong>{name.label}</strong>
                                    <code className="pm-key">{name.key}</code>
                                  </span>
                                  <span className="permissions-risk-badge permissions-risk-high">
                                    {riskLabel(permission)}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )}

                {canWriteAssignments && !targetHasBuiltinAccess ? (
                  <div className={`pm-savebar${isDirty ? " dirty" : ""}`}>
                    <span className="pm-savebar-summary">
                      {isSaving
                        ? `正在写入 ${saveProgress.done} / ${saveProgress.total}`
                        : isDirty
                          ? `待新增 ${diff.grants.length} 项 · 待撤销 ${diff.revokes.length} 项${
                              diff.highRiskGrants.length > 0
                                ? ` · 含 ${diff.highRiskGrants.length} 项高风险`
                                : ""
                            }`
                          : "没有未保存的改动"}
                    </span>
                    <button
                      className="secondary-button"
                      disabled={!isDirty || isSaving}
                      onClick={discardDraft}
                      type="button"
                    >
                      <Undo2 aria-hidden="true" size={16} />
                      放弃
                    </button>
                    <button
                      className="primary-button"
                      disabled={!isDirty || isSaving || isAssignmentsLoading}
                      onClick={() => void saveDraft()}
                      type="button"
                    >
                      {isSaving ? (
                        <LoaderCircle aria-hidden="true" className="spin" size={16} />
                      ) : (
                        <Save aria-hidden="true" size={16} />
                      )}
                      保存
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      ) : null}

      {hasData && activeTab === "permission" ? (
        <div className="permissions-product-stack module-control-org-list">
          {canViewControlPlanePermissions && controlPlaneModule ? (
            <section
              aria-label="系统权限"
              className={`ops-panel${
                collapsedGroups.has("control") ? " collapsed" : ""
              }`}
            >
              <div className="ops-panel-heading">
                <div>
                  <h3>系统权限</h3>
                  <p>仅 owner 可查看的控制面权限，不可分配。</p>
                </div>
                <div className="pm-head-tools">
                  <span className="ops-source">{controlPlaneCount} 项</span>
                  <button
                    aria-label="折叠"
                    className="mm-org-chev"
                    onClick={() => toggleGroup("control")}
                    type="button"
                  >
                    <ChevronDown aria-hidden="true" size={15} />
                  </button>
                </div>
              </div>
              <div className="permissions-card-grid">
                {controlPlaneModule.permissions.map((permission) => (
                  <PermissionCard
                    key={permission.permission_key}
                    permission={permission}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {grantableModules.map((moduleNode) => {
            const groupId = `feat:${moduleNode.moduleKey}`;
            const collapsed = collapsedGroups.has(groupId);
            return (
              <section
                aria-label={moduleNode.title}
                className={`ops-panel${collapsed ? " collapsed" : ""}`}
                key={groupId}
              >
                <div className="ops-panel-heading">
                  <div>
                    <h3>{moduleNode.title}</h3>
                    <p>点击卡片查看哪些员工拥有该权限。</p>
                  </div>
                  <div className="pm-head-tools">
                    <span className="ops-source">
                      {moduleNode.permissions.length} 项
                    </span>
                    <button
                      aria-label="折叠"
                      className="mm-org-chev"
                      onClick={() => toggleGroup(groupId)}
                      type="button"
                    >
                      <ChevronDown aria-hidden="true" size={15} />
                    </button>
                  </div>
                </div>
                <div className="permissions-card-grid">
                  {moduleNode.permissions.map((permission) => (
                    <PermissionCard
                      key={permission.permission_key}
                      disabled={isDialogLoading || pendingUserId !== null}
                      onClick={() => openPermissionDialog(permission)}
                      permission={permission}
                    />
                  ))}
                </div>
              </section>
            );
          })}

          {grantableModules.length === 0 && !controlPlaneModule ? (
            <div className="ops-empty-state">
              <strong>暂无数据</strong>
              <span>当前没有可显示的权限。</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {selectedPermission ? (
        <div
          aria-labelledby="permission-assignment-title"
          aria-modal="true"
          className="permissions-modal-backdrop"
          role="dialog"
        >
          <section className="permissions-modal">
            <div className="permissions-modal-heading">
              <div>
                <span className="eyebrow">功能权限</span>
                <h3 id="permission-assignment-title">
                  {splitPermissionDisplayName(selectedPermission).label}
                </h3>
                <code className="pm-key">
                  {splitPermissionDisplayName(selectedPermission).key}
                </code>
              </div>
              <button
                aria-label="关闭"
                className="icon-button"
                disabled={pendingUserId !== null}
                onClick={() => setSelectedPermission(null)}
                title="关闭"
                type="button"
              >
                <X aria-hidden="true" size={18} />
              </button>
            </div>

            {dialogError ? (
              <div className="users-alert users-alert-error" role="alert">
                <ShieldAlert aria-hidden="true" size={18} />
                <span>{dialogError}</span>
              </div>
            ) : null}

            {dialogNotice ? (
              <div className="users-alert users-alert-success" role="status">
                <CheckCircle2 aria-hidden="true" size={18} />
                <span>{dialogNotice}</span>
              </div>
            ) : null}

            <label className="field-group">
              <span>搜索员工</span>
              <span className="input-shell">
                <Search aria-hidden="true" size={16} />
                <input
                  onChange={(event) => setDialogSearchQuery(event.target.value)}
                  placeholder="员工姓名"
                  type="search"
                  value={dialogSearchQuery}
                />
              </span>
            </label>

            {isDialogLoading ? (
              <div className="list-state permissions-empty">
                <LoaderCircle className="spin" aria-hidden="true" size={22} />
                正在加载员工
              </div>
            ) : (
              <div className="permissions-user-list">
                {filteredDialogUsers.map((targetUser) => {
                  const assignment = dialogAssignments[targetUser.id] ?? null;
                  const checked = assignment?.enabled === true;
                  const isPending = pendingUserId === targetUser.id;
                  const disabled = !canWriteAssignments || pendingUserId !== null;

                  return (
                    <label className="permissions-user-row" key={targetUser.id}>
                      <input
                        checked={checked}
                        disabled={disabled}
                        onChange={(event) =>
                          void handleUserPermissionToggle(
                            targetUser,
                            event.target.checked,
                          )
                        }
                        type="checkbox"
                      />
                      <span>
                        <strong>{managedUserDisplayName(targetUser)}</strong>
                        <small>
                          {[
                            managedUserDisplayName(targetUser) !== targetUser.username
                              ? targetUser.username
                              : null,
                            targetUser.job_title,
                            targetUser.organization,
                          ]
                            .filter(Boolean)
                            .join(" / ") || roleLabel(targetUser.role)}
                        </small>
                      </span>
                      {isPending ? (
                        <LoaderCircle aria-hidden="true" className="spin" size={17} />
                      ) : checked ? (
                        <ShieldCheck aria-hidden="true" size={17} />
                      ) : null}
                    </label>
                  );
                })}
                {filteredDialogUsers.length === 0 ? (
                  <div className="ops-empty-state">
                    <strong>暂无数据</strong>
                    <span>请更换搜索条件。</span>
                  </div>
                ) : null}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
