"use client";

import {
  CheckCircle2,
  LoaderCircle,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  HIGH_RISK_CONFIRMATION_TEXT,
  canManagePermissionAssignments,
  canViewPermissionCenter,
  detectHighRiskPermission,
  filterGrantablePermissionRegistry,
  filterPermissionRegistryForRole,
  formatPermissionAssignmentsApiError,
  getPermissionCategoryLabel,
  getPermissionDisplayName,
  getPermissionUiCategory,
  grantUserPermissionAssignment,
  listPermissionRegistry,
  listUserPermissionAssignments,
  revokeUserPermissionAssignment,
  updateUserPermissionAssignment,
  type PermissionAssignment,
  type PermissionRegistryItem,
  type PermissionUiCategory,
} from "@/lib/permission-management-api";
import {
  formatUsersApiError,
  listUsers,
  type ManagedUser,
} from "@/lib/users-api";

const ASSIGNMENT_REASON = "Permission center assignment update.";
const GLOBAL_SCOPE_TYPE = "global";
const GLOBAL_SCOPE_KEY = "*";

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

function groupPermissions(
  permissions: PermissionRegistryItem[],
  category: PermissionUiCategory,
) {
  return permissions.filter(
    (permission) => getPermissionUiCategory(permission) === category,
  );
}

function userSearchText(user: ManagedUser) {
  return [
    user.username,
    user.job_title ?? "",
    user.organization_id ?? "",
    user.role,
  ]
    .join(" ")
    .toLowerCase();
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
  const content = (
    <>
      <span className="permissions-card-kicker">
        {getPermissionCategoryLabel(getPermissionUiCategory(permission))}
      </span>
      <strong>{getPermissionDisplayName(permission)}</strong>
      <small>{permission.description || permission.label}</small>
      <span
        className={
          detectHighRiskPermission(permission)
            ? "permissions-risk-badge permissions-risk-high"
            : "permissions-risk-badge"
        }
      >
        {permission.risk_level.toUpperCase()}
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
  const role = user?.role ?? "";
  const canView = status === "authenticated" && canViewPermissionCenter(role);
  const canWriteAssignments = canManagePermissionAssignments(role);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [registry, setRegistry] = useState<PermissionRegistryItem[]>([]);
  const [selectedPermission, setSelectedPermission] =
    useState<PermissionRegistryItem | null>(null);
  const [dialogAssignments, setDialogAssignments] = useState<
    Record<number, PermissionAssignment | null>
  >({});
  const [dialogSearchQuery, setDialogSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDialogLoading, setIsDialogLoading] = useState(false);
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [dialogNotice, setDialogNotice] = useState("");

  const visibleRegistry = useMemo(
    () =>
      filterPermissionRegistryForRole(
        filterGrantablePermissionRegistry(registry),
        role,
      ),
    [registry, role],
  );
  const controlPlanePermissions = useMemo(
    () => groupPermissions(visibleRegistry, "control_plane"),
    [visibleRegistry],
  );
  const featurePermissions = useMemo(
    () => groupPermissions(visibleRegistry, "feature"),
    [visibleRegistry],
  );
  const assignableUsers = useMemo(
    () => users.filter((targetUser) => targetUser.role !== "owner"),
    [users],
  );
  const filteredDialogUsers = useMemo(() => {
    const query = dialogSearchQuery.trim().toLowerCase();
    if (!query) {
      return assignableUsers;
    }
    return assignableUsers.filter((targetUser) =>
      userSearchText(targetUser).includes(query),
    );
  }, [assignableUsers, dialogSearchQuery]);

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
        formatUsersApiError(
          loadError,
          "Permission center users could not be loaded.",
        ),
      );
    }

    try {
      const registryResult = await listPermissionRegistry();
      setRegistry(registryResult);
    } catch (loadError) {
      loadErrors.push(
        formatUsersApiError(
          loadError,
          "Permission registry could not be loaded.",
        ),
      );
    }

    if (loadErrors.length > 0) {
      setError(loadErrors.join(" "));
    }
    setIsLoading(false);
  }, [canView]);

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
      let lastError: unknown = null;
      for (const targetUser of targetUsers) {
        try {
          const response = await listUserPermissionAssignments(targetUser.id);
          rows[targetUser.id] = permissionAssignmentForUser(
            response.assignments,
            permission.permission_key,
          );
        } catch (assignmentError) {
          failedCount += 1;
          lastError = assignmentError;
        }
      }
      setDialogAssignments((current) => ({
        ...current,
        ...rows,
      }));
      if (failedCount > 0) {
        setDialogError(
          `${formatPermissionAssignmentsApiError(lastError)} Showing loaded employees where available.`,
        );
      }
      setIsDialogLoading(false);
    },
    [canWriteAssignments],
  );

  useEffect(() => {
    void load();
  }, [load]);

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

    const highRisk = detectHighRiskPermission(selectedPermission);
    const confirmation = highRisk
      ? {
          confirm_high_risk: true,
          confirmation_text: HIGH_RISK_CONFIRMATION_TEXT,
        }
      : {};
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
      setDialogNotice("Permission assignment updated.");
    } catch (actionError) {
      setDialogError(formatPermissionAssignmentsApiError(actionError));
    } finally {
      setPendingUserId(null);
    }
  }

  if (!canView) {
    return null;
  }

  return (
    <section className="product-console" aria-label="Permissions">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Users & Organizations</span>
          <h2>Permissions</h2>
          <p>
            Human-readable permission groups with organization-scoped employee
            assignment controls.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Employees</span>
          <strong>{users.length}</strong>
        </div>
        <div>
          <span>Feature</span>
          <strong>{featurePermissions.length}</strong>
        </div>
        <div>
          <span>Control</span>
          <strong>{controlPlanePermissions.length}</strong>
        </div>
        <div>
          <span>Role</span>
          <strong>{role || "Unknown"}</strong>
        </div>
      </div>

      {isLoading && registry.length === 0 && users.length === 0 ? (
        <section className="list-state">
          <LoaderCircle className="spin" aria-hidden="true" size={22} />
          <span>Loading permission center</span>
        </section>
      ) : null}

      {error ? (
        <section className="list-state list-error" role="alert">
          <div>
            <h2>
              {registry.length > 0 || users.length > 0
                ? "Permissions are degraded"
                : "Permissions are unavailable"}
            </h2>
            <p>{error}</p>
            {registry.length > 0 || users.length > 0 ? (
              <p>Showing the last successful permission center data.</p>
            ) : null}
          </div>
          <button
            className="primary-button"
            onClick={() => void load()}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        </section>
      ) : null}

      {(!error || registry.length > 0 || users.length > 0) &&
      (!isLoading || registry.length > 0 || users.length > 0) ? (
        <div className="permissions-product-stack">
          {role === "owner" ? (
            <section
              className="permissions-group-section"
              aria-label="Control Plane Permissions"
            >
              <div className="permissions-section-heading">
                <h3>Control Plane Permissions</h3>
                <p>System, execution, module, adapter, and registry access.</p>
              </div>
              {controlPlanePermissions.length > 0 ? (
                <div className="permissions-card-grid">
                  {controlPlanePermissions.map((permission) => (
                    <PermissionCard
                      key={permission.permission_key}
                      permission={permission}
                    />
                  ))}
                </div>
              ) : (
                <div className="ops-empty-state">
                  <strong>No control plane permissions returned.</strong>
                  <span>Registry is empty for this group.</span>
                </div>
              )}
            </section>
          ) : null}

          <section
            className="permissions-group-section"
            aria-label="Feature Permissions"
          >
            <div className="permissions-section-heading">
              <h3>Feature Permissions</h3>
              <p>Agents, artifacts, reviews, and approvals.</p>
            </div>
            {featurePermissions.length > 0 ? (
              <div className="permissions-card-grid">
                {featurePermissions.map((permission) => (
                  <PermissionCard
                    key={permission.permission_key}
                    disabled={isDialogLoading || pendingUserId !== null}
                    onClick={() => openPermissionDialog(permission)}
                    permission={permission}
                  />
                ))}
              </div>
            ) : (
              <div className="ops-empty-state">
                <strong>No feature permissions returned.</strong>
                <span>Registry is empty for this group.</span>
              </div>
            )}
          </section>
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
                <span className="eyebrow">Feature Permissions</span>
                <h3 id="permission-assignment-title">
                  {getPermissionDisplayName(selectedPermission)}
                </h3>
              </div>
              <button
                aria-label="Close"
                className="icon-button"
                disabled={pendingUserId !== null}
                onClick={() => setSelectedPermission(null)}
                title="Close"
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
              <span>Search employees</span>
              <span className="input-shell">
                <Search aria-hidden="true" size={16} />
                <input
                  onChange={(event) =>
                    setDialogSearchQuery(event.target.value)
                  }
                  placeholder="employee name"
                  type="search"
                  value={dialogSearchQuery}
                />
              </span>
            </label>

            {isDialogLoading ? (
              <div className="list-state permissions-empty">
                <LoaderCircle className="spin" aria-hidden="true" size={22} />
                Loading employees
              </div>
            ) : (
              <div className="permissions-user-list">
                {filteredDialogUsers.map((targetUser) => {
                  const assignment = dialogAssignments[targetUser.id] ?? null;
                  const checked = assignment?.enabled === true;
                  const isPending = pendingUserId === targetUser.id;
                  const disabled = !canWriteAssignments || pendingUserId !== null;

                  return (
                    <label
                      className="permissions-user-row"
                      key={targetUser.id}
                    >
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
                        <strong>{targetUser.username}</strong>
                        <small>
                          {[targetUser.job_title, targetUser.organization_id]
                            .filter(Boolean)
                            .join(" / ") || targetUser.role}
                        </small>
                      </span>
                      {isPending ? (
                        <LoaderCircle
                          aria-hidden="true"
                          className="spin"
                          size={17}
                        />
                      ) : checked ? (
                        <ShieldCheck aria-hidden="true" size={17} />
                      ) : null}
                    </label>
                  );
                })}
                {filteredDialogUsers.length === 0 ? (
                  <div className="ops-empty-state">
                    <strong>No employees found.</strong>
                    <span>Try another name.</span>
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
