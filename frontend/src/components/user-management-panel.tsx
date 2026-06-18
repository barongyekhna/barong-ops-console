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
  ShieldCheck,
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
import { UserPermissionsPanel } from "@/components/user-permissions-panel";
import {
  MANAGED_USER_ROLES,
  createUser,
  disableUser,
  enableUser,
  formatUsersApiError,
  getUser,
  isManagedUserRole,
  listUserRoles,
  listUsers,
  resetUserPassword,
  updateUser,
  type ManagedUser,
  type ManagedUserRole,
  type UserRoleMetadata,
  type UserRolesResponse,
} from "@/lib/users-api";

const PASSWORD_LENGTH_MESSAGE =
  "Password must be 12 to 256 characters.";
const RESERVED_ROLE_NAMES = [
  "owner",
  "super_admin",
  "module_admin",
  "bot_agent",
] as const;
const RESERVED_ROLE_NOTES: Record<string, string> = {
  bot_agent: "Automation accounts require a separate identity and token setup.",
  module_admin: "Area Admin requires scoped access first.",
  owner: "Owner remains bootstrap-only and cannot be created through /users.",
  super_admin: "Super Admin will be enabled when advanced access controls are available.",
};
const FALLBACK_ROLE_METADATA: UserRoleMetadata[] = [
  {
    assignable: false,
    c04_status: "bootstrap_only",
    description: "Bootstrap/system owner account.",
    human_or_agent: "human",
    label: "Owner",
    name: "owner",
  },
  {
    assignable: false,
    c04_status: "reserved_no_permissions",
    description: "Reserved standard role with no workspace permissions.",
    human_or_agent: "human",
    label: "Super Admin",
    name: "super_admin",
  },
  {
    assignable: false,
    c04_status: "reserved_until_c05_c07",
    description: "Reserved until area-level access is available.",
    human_or_agent: "human",
    label: "Area Admin",
    name: "module_admin",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "Assignable managed user role.",
    human_or_agent: "human",
    label: "Viewer",
    name: "viewer",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "Assignable managed user role.",
    human_or_agent: "human",
    label: "Operator",
    name: "operator",
  },
  {
    assignable: true,
    c04_status: "assignable_user_role",
    description: "Assignable managed user role.",
    human_or_agent: "human",
    label: "Reviewer",
    name: "reviewer",
  },
  {
    assignable: false,
    c04_status: "reserved_no_login_flow",
    description: "Reserved for future automation accounts.",
    human_or_agent: "agent",
    label: "Automation Account",
    name: "bot_agent",
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
    return "Not recorded";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
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

export function UserManagementPanel() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [roleCatalog, setRoleCatalog] =
    useState<UserRolesResponse | null>(null);
  const [isRoleCatalogLoading, setIsRoleCatalogLoading] = useState(true);
  const [roleCatalogError, setRoleCatalogError] = useState("");
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
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] =
    useState<ManagedUserRole>("viewer");

  const isOwner = currentUser?.role === "owner";
  const isBusy = pendingAction !== null;

  const loadRoleCatalog = useCallback(async () => {
    if (!isOwner) {
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
      setRoleCatalog(null);
      setRoleCatalogError(
        formatUsersApiError(
          error,
          "The role catalog could not be loaded.",
        ),
      );
    } finally {
      setIsRoleCatalogLoading(false);
    }
  }, [isOwner]);

  const loadUsers = useCallback(
    async (showLoading = true) => {
      if (!isOwner) {
        setIsLoading(false);
        return;
      }

      if (showLoading) {
        setIsLoading(true);
      }
      setListError("");

      try {
        const result = await listUsers();
        setUsers(result.items);
      } catch (error) {
        setUsers([]);
        setListError(
          formatUsersApiError(
            error,
            "The user list could not be loaded.",
          ),
        );
      } finally {
        if (showLoading) {
          setIsLoading(false);
        }
      }
    },
    [isOwner],
  );

  useEffect(() => {
    void loadRoleCatalog();
  }, [loadRoleCatalog]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const catalogRoleByName = useMemo(
    () =>
      new Map(
        (roleCatalog?.standard_roles ?? []).map((role) => [
          role.name,
          role,
        ]),
      ),
    [roleCatalog],
  );

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

  const reservedRoleOptions = useMemo(
    () =>
      RESERVED_ROLE_NAMES.map(
        (role) =>
          roleCatalog?.standard_roles.find((entry) => entry.name === role) ??
          FALLBACK_ROLE_METADATA_BY_NAME.get(role),
      ).filter((role): role is UserRoleMetadata => Boolean(role)),
    [roleCatalog],
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
  const expandedRoleMetadata = expandedUser
    ? catalogRoleByName.get(expandedUser.role)
    : null;

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
    const passwordError = validatePassword(createPassword);
    if (!username) {
      setActionError("Username is required.");
      return;
    }
    if (passwordError) {
      setActionError(passwordError);
      return;
    }
    if (
      !isManagedUserRole(createRole) ||
      !assignableRoleNames.has(createRole)
    ) {
      setActionError(
        "Choose one of the current assignable roles before creating the account.",
      );
      return;
    }

    setPendingAction("create");
    try {
      const created = await createUser({
        password: createPassword,
        role: createRole,
        username,
      });
      setActionNotice(`Created account ${created.username}.`);
      setCreateUsername("");
      setCreateRole("viewer");
      await refreshAfterMutation(created.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The account could not be created."),
      );
    } finally {
      setCreatePassword("");
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
        formatUsersApiError(error, "The user detail could not be loaded."),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleOpenPermissions(target: ManagedUser) {
    clearActionMessages();
    if (expandedUser?.id === target.id) {
      return;
    }

    setPendingAction(`detail-${target.id}`);
    try {
      await refreshDetail(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The user detail could not be loaded."),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleDisable(target: ManagedUser) {
    clearActionMessages();
    if (target.id === currentUser?.id) {
      setActionError("You cannot disable your own owner account here.");
      return;
    }
    if (
      !window.confirm(
        `Disable ${target.username}? This account will no longer be able to sign in.`,
      )
    ) {
      return;
    }

    setPendingAction(`disable-${target.id}`);
    try {
      const updated = await disableUser(target.id);
      setActionNotice(`Disabled account ${updated.username}.`);
      await refreshAfterMutation(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The account could not be disabled."),
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function handleEnable(target: ManagedUser) {
    clearActionMessages();
    if (!window.confirm(`Enable ${target.username}?`)) {
      return;
    }

    setPendingAction(`enable-${target.id}`);
    try {
      const updated = await enableUser(target.id);
      setActionNotice(`Enabled account ${updated.username}.`);
      await refreshAfterMutation(target.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The account could not be enabled."),
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
      setActionError("You cannot change your own owner role here.");
      return;
    }
    if (!isManagedUserRole(expandedUser.role)) {
      setActionError("Only managed sub-account roles can be updated here.");
      return;
    }
    if (
      !isManagedUserRole(detailRole) ||
      !assignableRoleNames.has(detailRole)
    ) {
      setActionError(
        "Choose one of the current assignable roles before saving.",
      );
      return;
    }

    setPendingAction(`role-${expandedUser.id}`);
    try {
      const updated = await updateUser(expandedUser.id, { role: detailRole });
      setActionNotice(`Updated role for ${updated.username}.`);
      await refreshAfterMutation(expandedUser.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The account role could not be updated."),
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
      setActionError("You cannot reset your own owner password here.");
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
        `Reset password for ${resetTarget.username}? The old password will stop working.`,
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
      setActionNotice(`Reset password for ${updated.username}.`);
      setResetTarget(null);
      await refreshAfterMutation(resetTarget.id);
    } catch (error) {
      setActionError(
        formatUsersApiError(error, "The password could not be reset."),
      );
    } finally {
      setResetPassword("");
      setPendingAction(null);
    }
  }

  if (!isOwner) {
    return (
      <section className="list-state list-error" role="alert">
        <div>
          <h2>User management is owner-only</h2>
          <p>
            This signed-in account can use the console, but only owner accounts
            can manage internal users.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="users-workspace" aria-label="User management">
      <form className="users-create-panel" onSubmit={handleCreate}>
        <div className="users-panel-heading">
          <div>
            <span className="eyebrow">Internal accounts</span>
            <h3>Create user</h3>
            <p>
              Owner-created console accounts only. This is not public
              registration.
            </p>
          </div>
          <UserRoundCog aria-hidden="true" size={24} />
        </div>

        <div className="users-form-grid">
          <label className="field-group">
            <span>Username</span>
            <span className="input-shell">
              <input
                autoComplete="off"
                disabled={isBusy}
                maxLength={255}
                onChange={(event) => setCreateUsername(event.target.value)}
                placeholder="managed_viewer"
                type="text"
                value={createUsername}
              />
            </span>
          </label>

          <label className="field-group">
            <span>Password</span>
            <span className="input-shell">
              <input
                autoComplete="new-password"
                disabled={isBusy}
                maxLength={256}
                minLength={12}
                onChange={(event) => setCreatePassword(event.target.value)}
                placeholder="12+ characters"
                type="password"
                value={createPassword}
              />
            </span>
          </label>

          <label className="field-group">
            <span>Role</span>
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
                  {role.label}
                </option>
              ))}
            </select>
            <span className="users-field-note">
              {isRoleCatalogLoading
                ? "Loading owner-only role catalog."
                : roleCatalogError
                  ? "Using safe fallback roles after the role catalog failed."
                  : "Loaded from /users/roles."}
            </span>
          </label>
        </div>

        <button
          className="primary-button users-submit-button"
          disabled={
            isBusy ||
            isRoleCatalogLoading ||
            assignableRoleOptions.length === 0
          }
          type="submit"
        >
          {pendingAction === "create" ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          Create user
        </button>
      </form>

      <section className="users-role-catalog-panel" aria-label="Role catalog">
        <div className="users-panel-heading">
          <div>
            <span className="eyebrow">Role catalog</span>
            <h3>Roles</h3>
            <p>
              Users reads role labels and selectable roles from the owner-only
              role catalog.
            </p>
          </div>
          <button
            className="secondary-button"
            disabled={isBusy || isRoleCatalogLoading}
            onClick={() => void loadRoleCatalog()}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
            Refresh roles
          </button>
        </div>

        {isRoleCatalogLoading ? (
          <div className="list-state" aria-label="Loading role catalog">
            <LoaderCircle className="spin" aria-hidden="true" size={22} />
            Loading role catalog
          </div>
        ) : null}

        {!isRoleCatalogLoading && roleCatalogError ? (
          <div className="users-alert users-alert-warning" role="status">
            <ShieldAlert aria-hidden="true" size={18} />
            <span>
              {roleCatalogError} Safe fallback roles are limited to viewer,
              operator, and reviewer.
            </span>
          </div>
        ) : null}

        {!isRoleCatalogLoading ? (
          <div className="users-role-catalog-grid">
            <div className="users-role-group">
              <h4>Current assignable roles</h4>
              <ul>
                {assignableRoleOptions.map((role) => (
                  <li key={role.name}>
                    <span>{role.label}</span>
                    <p>{role.description}</p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="users-role-group">
              <h4>Reserved roles</h4>
              <ul>
                {reservedRoleOptions.map((role) => (
                  <li key={role.name}>
                    <span>{role.label}</span>
                    <p>
                      {role.description} {RESERVED_ROLE_NOTES[role.name]}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="users-muted-note">
                Advanced access controls will be enabled when they are ready.
              </p>
            </div>
          </div>
        ) : null}
      </section>

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
            <span className="eyebrow">Password reset</span>
            <h3>{resetTarget.username}</h3>
            <p>
              Enter a new temporary password. It will not be shown after this
              form is submitted.
            </p>
          </div>
          <label className="field-group">
            <span>New password</span>
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
              Confirm reset
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
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      <div className="users-list-panel">
        <div className="users-list-heading">
          <div>
            <h3>Users</h3>
            <p>{users.length} accounts returned by the owner-only API.</p>
          </div>
          <button
            className="secondary-button"
            disabled={isBusy || isLoading}
            onClick={() => void loadUsers()}
            type="button"
          >
            <RotateCcw aria-hidden="true" size={17} />
            Refresh
          </button>
        </div>

        {isLoading ? (
          <div className="list-state" aria-label="Loading users">
            <LoaderCircle className="spin" aria-hidden="true" size={22} />
            Loading users
          </div>
        ) : null}

        {!isLoading && listError ? (
          <div className="list-state list-error" role="alert">
            <div>
              <h2>User API request failed</h2>
              <p>{listError}</p>
            </div>
            <button
              className="primary-button"
              onClick={() => void loadUsers()}
              type="button"
            >
              <RotateCcw aria-hidden="true" size={17} />
              Retry
            </button>
          </div>
        ) : null}

        {!isLoading && !listError ? (
          <div className="users-table-scroll">
            <table className="users-table">
              <thead>
                <tr>
                  <th scope="col">Username</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedUsers.map((target) => {
                  const isSelf = target.id === currentUser?.id;
                  const actionDisabled = isBusy || isSelf;
                  const rowPending =
                    pendingAction?.endsWith(`-${target.id}`) ?? false;
                  const roleMetadata = catalogRoleByName.get(target.role);

                  return (
                    <tr key={target.id}>
                      <td>
                        <strong>{target.username}</strong>
                        {isSelf ? <span>Current account</span> : null}
                      </td>
                      <td>
                        <div className="users-role-cell">
                          <span className="users-role-pill">
                            {roleMetadata?.label ?? target.role}
                          </span>
                          {roleMetadata ? (
                            <span className="users-role-description">
                              {roleMetadata.description}
                            </span>
                          ) : null}
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
                          {target.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td>{formatDate(target.created_at)}</td>
                      <td>{formatDate(target.updated_at)}</td>
                      <td>
                        <div className="users-actions">
                          <button
                            className="icon-button"
                            disabled={isBusy}
                            onClick={() => void handleViewDetails(target)}
                            title="View details"
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

                          <button
                            className="secondary-button"
                            disabled={isBusy}
                            onClick={() => void handleOpenPermissions(target)}
                            title="Manage permissions"
                            type="button"
                          >
                            {pendingAction === `detail-${target.id}` ? (
                              <LoaderCircle
                                className="spin"
                                aria-hidden="true"
                                size={17}
                              />
                            ) : (
                              <ShieldCheck aria-hidden="true" size={17} />
                            )}
                            Permissions
                          </button>

                          {target.is_active ? (
                            <button
                              className="secondary-button"
                              disabled={actionDisabled}
                              onClick={() => void handleDisable(target)}
                              title={
                                isSelf
                                  ? "You cannot disable yourself"
                                  : "Disable user"
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
                              Disable
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
                              Enable
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
                                ? "You cannot reset your own password here"
                                : "Reset password"
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
                            Reset
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {expandedUser ? (
        <section className="user-detail-panel" aria-label="User detail">
          <div className="users-panel-heading">
            <div>
              <span className="eyebrow">User detail</span>
              <h3>{expandedUser.username}</h3>
            </div>
            <button
              className="icon-button"
              onClick={() => setExpandedUser(null)}
              title="Close details"
              type="button"
            >
              <Eye aria-hidden="true" size={17} />
            </button>
          </div>

          <dl className="user-detail-grid">
            <div>
              <dt>User ID</dt>
              <dd>{expandedUser.id}</dd>
            </div>
            <div>
              <dt>Username</dt>
              <dd>{expandedUser.username}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>
                {expandedRoleMetadata?.label ?? expandedUser.role}
                {expandedRoleMetadata ? (
                  <span className="user-detail-description">
                    {expandedRoleMetadata.description}
                  </span>
                ) : null}
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{expandedUser.is_active ? "Active" : "Disabled"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(expandedUser.created_at)}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{formatDate(expandedUser.updated_at)}</dd>
            </div>
            <div>
              <dt>Last login</dt>
              <dd>{formatDate(expandedUser.last_login_at)}</dd>
            </div>
          </dl>

          {isManagedUserRole(expandedUser.role) ? (
            <form className="users-role-form" onSubmit={handleRoleUpdate}>
              <label className="field-group">
                <span>Managed role</span>
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
                      {role.label}
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
                Save role
              </button>
            </form>
          ) : (
            <p className="users-muted-note">
              Owner and reserved roles are displayed for audit context. Owner,
              super admin, area admin, and automation account roles cannot be
              changed here.
            </p>
          )}

          <UserPermissionsPanel targetUser={expandedUser} />
        </section>
      ) : null}
    </section>
  );
}
