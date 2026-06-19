"use client";

import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  type FormEvent,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  EMPTY_ASSIGNMENTS_NOTICE,
  HIGH_RISK_CONFIRMATION_TEXT,
  OWNER_FULL_ACCESS_NOTICE,
  ROLE_DEFAULT_PERMISSIONS_NOTICE,
  detectHighRiskPermission,
  filterGrantablePermissionRegistry,
  formatPermissionAssignmentsApiError,
  getAssignmentEmptyStateText,
  getPermissionDisplayName,
  getPermissionTargetMode,
  grantUserPermissionAssignment,
  listPermissionRegistry,
  listUserPermissionAssignments,
  matchesPermissionRegistrySearch,
  requiresHighRiskUpdateConfirmation,
  revokeUserPermissionAssignment,
  shouldRefreshAssignmentsAfterMutation,
  updateUserPermissionAssignment,
  validatePermissionGrantInput,
  validatePermissionRevokeInput,
  validatePermissionUpdateInput,
  type PermissionAssignment,
  type PermissionAssignmentListResponse,
  type PermissionRegistryItem,
} from "@/lib/permission-management-api";
import type { ManagedUser } from "@/lib/users-api";

const SCOPE_OPTIONS = [
  "global",
  "module",
  "company",
  "factory",
  "department",
  "organization",
] as const;

const SCOPE_LABELS: Record<(typeof SCOPE_OPTIONS)[number], string> = {
  company: "Company",
  department: "Department",
  factory: "Factory",
  global: "Workspace",
  module: "Area",
  organization: "Organization",
};

type GrantFormState = {
  permission_key: string;
  scope_type: string;
  scope_id: string;
  expires_at: string;
  reason: string;
  enabled: boolean;
  confirm_high_risk: boolean;
  confirmation_text: string;
};

type EditFormState = {
  enabled: boolean;
  scope_type: string;
  scope_id: string;
  expires_at: string;
  reason: string;
  confirm_high_risk: boolean;
  confirmation_text: string;
};

const DEFAULT_GRANT_FORM: GrantFormState = {
  confirm_high_risk: false,
  confirmation_text: "",
  enabled: true,
  expires_at: "",
  permission_key: "",
  reason: "",
  scope_id: "*",
  scope_type: "global",
};

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

function toDateTimeLocalValue(value: string | null | undefined) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(0, 16);
  }

  const pad = (part: number) => String(part).padStart(2, "0");
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    "T",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
  ].join("");
}

function formatPermissionLabel(permission: PermissionRegistryItem) {
  return getPermissionDisplayName(permission);
}

function assignmentRiskLabel(assignment: PermissionAssignment) {
  if (assignment.high_risk || detectHighRiskPermission(assignment)) {
    return "High risk";
  }

  return assignment.risk_level
    ? assignment.risk_level.toUpperCase()
    : "Normal";
}

function scopeLabel(scope: string) {
  return SCOPE_LABELS[scope as (typeof SCOPE_OPTIONS)[number]] ?? scope;
}

function createEditForm(assignment: PermissionAssignment): EditFormState {
  return {
    confirm_high_risk: false,
    confirmation_text: "",
    enabled: assignment.enabled,
    expires_at: toDateTimeLocalValue(assignment.expires_at),
    reason: assignment.reason ?? "",
    scope_id: assignment.scope_id || assignment.scope_key || "*",
    scope_type: assignment.scope_type || "global",
  };
}

export function UserPermissionsPanel({
  targetUser,
}: {
  targetUser: ManagedUser;
}) {
  const [registry, setRegistry] = useState<PermissionRegistryItem[]>([]);
  const [assignmentResponse, setAssignmentResponse] =
    useState<PermissionAssignmentListResponse | null>(null);
  const [isRegistryLoading, setIsRegistryLoading] = useState(false);
  const [isAssignmentsLoading, setIsAssignmentsLoading] = useState(true);
  const [registryError, setRegistryError] = useState("");
  const [assignmentsError, setAssignmentsError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [grantForm, setGrantForm] =
    useState<GrantFormState>(DEFAULT_GRANT_FORM);
  const [editingAssignmentId, setEditingAssignmentId] =
    useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditFormState | null>(null);
  const [revokeReasons, setRevokeReasons] = useState<Record<string, string>>(
    {},
  );

  const targetMode = getPermissionTargetMode(targetUser, assignmentResponse);
  const isOwnerTarget = targetMode === "owner_full_access";
  const isBusy = pendingAction !== null;

  const loadAssignments = useCallback(async () => {
    setIsAssignmentsLoading(true);
    setAssignmentsError("");
    try {
      setAssignmentResponse(
        await listUserPermissionAssignments(targetUser.id),
      );
    } catch (error) {
      setAssignmentResponse(null);
      setAssignmentsError(formatPermissionAssignmentsApiError(error));
    } finally {
      setIsAssignmentsLoading(false);
    }
  }, [targetUser.id]);

  const loadRegistry = useCallback(async () => {
    if (targetUser.role === "owner") {
      setRegistry([]);
      setRegistryError("");
      setIsRegistryLoading(false);
      return;
    }

    setIsRegistryLoading(true);
    setRegistryError("");
    try {
      setRegistry(await listPermissionRegistry());
    } catch (error) {
      setRegistry([]);
      setRegistryError(formatPermissionAssignmentsApiError(error));
    } finally {
      setIsRegistryLoading(false);
    }
  }, [targetUser.role]);

  useEffect(() => {
    setAssignmentResponse(null);
    setRegistry([]);
    setSearchQuery("");
    setGrantForm(DEFAULT_GRANT_FORM);
    setEditingAssignmentId(null);
    setEditForm(null);
    setRevokeReasons({});
    setActionError("");
    setActionNotice("");
    void loadAssignments();
    void loadRegistry();
  }, [loadAssignments, loadRegistry, targetUser.id]);

  const grantablePermissions = useMemo(
    () => filterGrantablePermissionRegistry(registry),
    [registry],
  );

  const filteredGrantPermissions = useMemo(
    () =>
      grantablePermissions.filter((permission) =>
        matchesPermissionRegistrySearch(permission, searchQuery),
      ),
    [grantablePermissions, searchQuery],
  );

  useEffect(() => {
    if (isOwnerTarget || filteredGrantPermissions.length === 0) {
      return;
    }

    if (
      !filteredGrantPermissions.some(
        (permission) =>
          permission.permission_key === grantForm.permission_key,
      )
    ) {
      setGrantForm((current) => ({
        ...current,
        permission_key: filteredGrantPermissions[0].permission_key,
      }));
    }
  }, [filteredGrantPermissions, grantForm.permission_key, isOwnerTarget]);

  const selectedGrantPermission = useMemo(
    () =>
      grantablePermissions.find(
        (permission) =>
          permission.permission_key === grantForm.permission_key,
      ) ?? null,
    [grantForm.permission_key, grantablePermissions],
  );
  const selectedGrantHighRisk = detectHighRiskPermission(
    selectedGrantPermission,
  );

  async function refreshAfterMutation(
    action: "grant" | "update" | "revoke",
  ) {
    if (shouldRefreshAssignmentsAfterMutation(action)) {
      await loadAssignments();
    }
  }

  async function handleGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError("");
    setActionNotice("");

    const validation = validatePermissionGrantInput({
      ...grantForm,
      permission: selectedGrantPermission,
    });
    if (!validation.ok) {
      setActionError(validation.message);
      return;
    }

    setPendingAction("grant");
    try {
      const result = await grantUserPermissionAssignment(
        targetUser.id,
        validation.payload,
      );

      if (
        validation.payload.enabled === false &&
        result.assignment?.id
      ) {
        await updateUserPermissionAssignment(
          targetUser.id,
          result.assignment.id,
          {
            enabled: false,
            reason: validation.payload.reason,
          },
        );
      }

      setActionNotice("Permission granted.");
      setGrantForm((current) => ({
        ...DEFAULT_GRANT_FORM,
        permission_key: current.permission_key,
      }));
      await refreshAfterMutation("grant");
    } catch (error) {
      setActionError(formatPermissionAssignmentsApiError(error));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleUpdate(
    event: FormEvent<HTMLFormElement>,
    assignment: PermissionAssignment,
  ) {
    event.preventDefault();
    setActionError("");
    setActionNotice("");
    if (!editForm) {
      return;
    }

    const validation = validatePermissionUpdateInput(assignment, editForm);
    if (!validation.ok) {
      setActionError(validation.message);
      return;
    }

    setPendingAction(`update-${assignment.id}`);
    try {
      await updateUserPermissionAssignment(
        targetUser.id,
        assignment.id,
        validation.payload,
      );
      setActionNotice("Permission updated.");
      setEditingAssignmentId(null);
      setEditForm(null);
      await refreshAfterMutation("update");
    } catch (error) {
      setActionError(formatPermissionAssignmentsApiError(error));
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRevoke(assignment: PermissionAssignment) {
    setActionError("");
    setActionNotice("");

    const validation = validatePermissionRevokeInput(
      assignment,
      revokeReasons[assignment.id] ?? "",
    );
    if (!validation.ok) {
      setActionError(validation.message);
      return;
    }

    if (
      !window.confirm(
        `Revoke ${getPermissionDisplayName(assignment)}? This will remove the explicit assignment.`,
      )
    ) {
      return;
    }

    setPendingAction(`revoke-${assignment.id}`);
    try {
      await revokeUserPermissionAssignment(
        targetUser.id,
        assignment.id,
        validation.payload,
      );
      setActionNotice("Permission revoked.");
      setRevokeReasons((current) => ({
        ...current,
        [assignment.id]: "",
      }));
      await refreshAfterMutation("revoke");
    } catch (error) {
      setActionError(formatPermissionAssignmentsApiError(error));
    } finally {
      setPendingAction(null);
    }
  }

  function startEdit(assignment: PermissionAssignment) {
    setActionError("");
    setActionNotice("");
    setEditingAssignmentId(assignment.id);
    setEditForm(createEditForm(assignment));
  }

  return (
    <section className="permissions-panel" aria-label="User permissions">
      <div className="users-panel-heading">
        <div>
          <span className="eyebrow">Permissions</span>
          <h3>User permissions</h3>
          <p>{ROLE_DEFAULT_PERMISSIONS_NOTICE}</p>
        </div>
        <button
          className="secondary-button"
          disabled={isBusy || isAssignmentsLoading}
          onClick={() => void loadAssignments()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          Refresh permissions
        </button>
      </div>

      {assignmentsError ? (
        <div className="users-alert users-alert-error" role="alert">
          <ShieldAlert aria-hidden="true" size={18} />
          <span>{assignmentsError}</span>
        </div>
      ) : null}

      {actionError ? (
        <div className="users-alert users-alert-error" role="alert">
          <ShieldAlert aria-hidden="true" size={18} />
          <span>{actionError}</span>
        </div>
      ) : null}

      {actionNotice ? (
        <div className="users-alert users-alert-success" role="status">
          <CheckCircle2 aria-hidden="true" size={18} />
          <span>{actionNotice}</span>
        </div>
      ) : null}

      {isAssignmentsLoading ? (
        <div className="list-state permissions-empty">
          <LoaderCircle className="spin" aria-hidden="true" size={22} />
          Loading permission assignments
        </div>
      ) : null}

      {!isAssignmentsLoading && isOwnerTarget ? (
        <div className="permissions-owner-note" role="status">
          <ShieldCheck aria-hidden="true" size={22} />
          <div>
            <h4>{OWNER_FULL_ACCESS_NOTICE}</h4>
            <p>
              {assignmentResponse?.owner_full_access_note ??
                "Owner access comes from the role and is not shown as a standard assignment."}
            </p>
          </div>
        </div>
      ) : null}

      {!isAssignmentsLoading && !isOwnerTarget ? (
        <>
          <section
            className="permissions-grant-section"
            aria-label="Grant permission"
          >
            <div className="permissions-section-heading">
              <h4>Grant permission</h4>
              <p>
                Choose one permission at a time. Wildcard and bulk grants are
                not available here.
              </p>
            </div>

            {registryError ? (
              <div className="users-alert users-alert-error" role="alert">
                <ShieldAlert aria-hidden="true" size={18} />
                <span>{registryError}</span>
              </div>
            ) : null}

            <form className="permissions-grant-form" onSubmit={handleGrant}>
              <label className="field-group permissions-search-field">
                <span>Search permissions</span>
                <span className="input-shell">
                  <Search aria-hidden="true" size={16} />
                  <input
                    disabled={isBusy || isRegistryLoading}
                    onChange={(event) =>
                      setSearchQuery(event.target.value)
                    }
                    placeholder="name, area, category"
                    type="search"
                    value={searchQuery}
                  />
                </span>
              </label>

              <label className="field-group">
                <span>Permission</span>
                <select
                  className="select-shell"
                  disabled={
                    isBusy ||
                    isRegistryLoading ||
                    filteredGrantPermissions.length === 0
                  }
                  onChange={(event) =>
                    setGrantForm((current) => ({
                      ...current,
                      permission_key: event.target.value,
                    }))
                  }
                  value={grantForm.permission_key}
                >
                  {filteredGrantPermissions.map((permission) => (
                    <option
                      key={permission.permission_key}
                      value={permission.permission_key}
                    >
                      {formatPermissionLabel(permission)}
                    </option>
                  ))}
                </select>
                <span className="users-field-note">
                  {isRegistryLoading
                    ? "Loading permissions."
                    : `${filteredGrantPermissions.length} grantable permissions shown.`}
                </span>
              </label>

              <label className="field-group">
                <span>Scope type</span>
                <select
                  className="select-shell"
                  disabled={isBusy}
                  onChange={(event) =>
                    setGrantForm((current) => ({
                      ...current,
                      scope_id:
                        event.target.value === "global"
                          ? "*"
                          : current.scope_id,
                      scope_type: event.target.value,
                    }))
                  }
                  value={grantForm.scope_type}
                >
                  {SCOPE_OPTIONS.map((scope) => (
                    <option key={scope} value={scope}>
                      {scopeLabel(scope)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field-group">
                <span>Scope ID</span>
                <span className="input-shell">
                  <input
                    disabled={isBusy || grantForm.scope_type === "global"}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        scope_id: event.target.value,
                      }))
                    }
                    placeholder="*"
                    type="text"
                    value={
                      grantForm.scope_type === "global"
                        ? "*"
                        : grantForm.scope_id
                    }
                  />
                </span>
              </label>

              <label className="field-group">
                <span>Expires at</span>
                <span className="input-shell">
                  <input
                    disabled={isBusy}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        expires_at: event.target.value,
                      }))
                    }
                    type="datetime-local"
                    value={grantForm.expires_at}
                  />
                </span>
              </label>

              <label className="field-group permissions-enabled-field">
                <span>Enabled</span>
                <span className="permissions-checkbox-line">
                  <input
                    checked={grantForm.enabled}
                    disabled={isBusy}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        enabled: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                  Enabled immediately
                </span>
              </label>

              <label className="field-group permissions-reason-field">
                <span>Reason</span>
                <span className="textarea-shell">
                  <textarea
                    disabled={isBusy}
                    maxLength={4000}
                    onChange={(event) =>
                      setGrantForm((current) => ({
                        ...current,
                        reason: event.target.value,
                      }))
                    }
                    placeholder="Why this explicit assignment is needed"
                    value={grantForm.reason}
                  />
                </span>
              </label>

              {selectedGrantHighRisk ? (
                <div className="permissions-risk-box" role="alert">
                  <AlertTriangle aria-hidden="true" size={18} />
                  <div>
                    <strong>
                      This permission affects administration, security,
                      releases, or user access. Confirm the reason before
                      granting it.
                    </strong>
                    <label className="permissions-checkbox-line">
                      <input
                        checked={grantForm.confirm_high_risk}
                        disabled={isBusy}
                        onChange={(event) =>
                          setGrantForm((current) => ({
                            ...current,
                            confirm_high_risk: event.target.checked,
                          }))
                        }
                        type="checkbox"
                      />
                      Confirm high-risk grant
                    </label>
                    <label className="field-group">
                      <span>
                        请输入 {HIGH_RISK_CONFIRMATION_TEXT} 以确认
                      </span>
                      <span className="input-shell">
                        <input
                          disabled={isBusy}
                          onChange={(event) =>
                            setGrantForm((current) => ({
                              ...current,
                              confirmation_text: event.target.value,
                            }))
                          }
                          type="text"
                          value={grantForm.confirmation_text}
                        />
                      </span>
                    </label>
                  </div>
                </div>
              ) : null}

              <button
                className="primary-button permissions-submit-button"
                disabled={
                  isBusy ||
                  isRegistryLoading ||
                  filteredGrantPermissions.length === 0
                }
                type="submit"
              >
                {pendingAction === "grant" ? (
                  <LoaderCircle className="spin" aria-hidden="true" size={17} />
                ) : (
                  <ShieldCheck aria-hidden="true" size={17} />
                )}
                Grant permission
              </button>
            </form>
          </section>

          <section
            className="permissions-assignment-section"
            aria-label="Explicit assignments"
          >
            <div className="permissions-section-heading">
              <h4>Explicit assignments</h4>
              <p>
                Owner full access is not listed here. Role default
                permissions still do not auto-apply.
              </p>
            </div>

            {assignmentResponse &&
            assignmentResponse.assignments.length === 0 ? (
              <div className="list-state permissions-empty">
                {getAssignmentEmptyStateText(assignmentResponse) ||
                  EMPTY_ASSIGNMENTS_NOTICE}
              </div>
            ) : null}

            {assignmentResponse &&
            assignmentResponse.assignments.length > 0 ? (
              <div className="permissions-table-scroll">
                <table className="permissions-table">
                  <thead>
                    <tr>
                      <th scope="col">Permission</th>
                      <th scope="col">Scope</th>
                      <th scope="col">Status</th>
                      <th scope="col">Audit</th>
                      <th scope="col">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignmentResponse.assignments.map((assignment) => {
                      const isEditing =
                        editingAssignmentId === assignment.id && editForm;
                      const revokeReason = revokeReasons[assignment.id] ?? "";
                      const assignmentHighRisk =
                        assignment.high_risk ||
                        detectHighRiskPermission(assignment);
                      const needsUpdateConfirmation =
                        isEditing && editForm
                          ? requiresHighRiskUpdateConfirmation(
                              assignment,
                              editForm,
                            )
                          : false;

                      return (
                        <Fragment
                          key={assignment.id || assignment.permission_key}
                        >
                          <tr>
                            <td>
                              <strong>{getPermissionDisplayName(assignment)}</strong>
                              <span>
                                {assignment.permission_name ??
                                  assignment.description ??
                                  "No description"}
                              </span>
                              <span
                                className={
                                  assignmentHighRisk
                                    ? "permissions-risk-badge permissions-risk-high"
                                    : "permissions-risk-badge"
                                }
                              >
                                {assignmentRiskLabel(assignment)}
                              </span>
                            </td>
                            <td>
                              <strong>{scopeLabel(assignment.scope_type)}</strong>
                              <span>{assignment.scope_id}</span>
                            </td>
                            <td>
                              <span
                                className={`users-status ${
                                  assignment.enabled
                                    ? "users-status-active"
                                    : "users-status-disabled"
                                }`}
                              >
                                {assignment.enabled ? "Enabled" : "Disabled"}
                              </span>
                              <span
                                className={`permissions-effective ${
                                  assignment.effective
                                    ? "permissions-effective-on"
                                    : "permissions-effective-off"
                                }`}
                              >
                                {assignment.effective
                                  ? "Effective"
                                  : "Not effective"}
                              </span>
                              <span>Expires: {formatDate(assignment.expires_at)}</span>
                            </td>
                            <td>
                              <span>
                                Granted by:{" "}
                                {assignment.granted_by_user_id ?? "Unknown"}
                              </span>
                              <span>Created: {formatDate(assignment.created_at)}</span>
                              <span>Updated: {formatDate(assignment.updated_at)}</span>
                              {assignment.reason ? (
                                <span>Reason: {assignment.reason}</span>
                              ) : null}
                            </td>
                            <td>
                              <div className="permissions-action-stack">
                                <div className="users-inline-actions">
                                  <button
                                    className="secondary-button"
                                    disabled={isBusy || !assignment.id}
                                    onClick={() => startEdit(assignment)}
                                    type="button"
                                  >
                                    <Save aria-hidden="true" size={17} />
                                    Update
                                  </button>
                                  <button
                                    className="danger-button"
                                    disabled={isBusy || !assignment.id}
                                    onClick={() => void handleRevoke(assignment)}
                                    type="button"
                                  >
                                    {pendingAction ===
                                    `revoke-${assignment.id}` ? (
                                      <LoaderCircle
                                        className="spin"
                                        aria-hidden="true"
                                        size={17}
                                      />
                                    ) : (
                                      <Trash2 aria-hidden="true" size={17} />
                                    )}
                                    Revoke
                                  </button>
                                </div>
                                <label className="field-group permissions-revoke-field">
                                  <span>
                                    {assignmentHighRisk
                                      ? "Revoke reason required"
                                      : "Revoke reason"}
                                  </span>
                                  <span className="input-shell">
                                    <input
                                      disabled={isBusy}
                                      maxLength={4000}
                                      onChange={(event) =>
                                        setRevokeReasons((current) => ({
                                          ...current,
                                          [assignment.id]: event.target.value,
                                        }))
                                      }
                                      placeholder="Reason for revoke"
                                      type="text"
                                      value={revokeReason}
                                    />
                                  </span>
                                </label>
                              </div>
                            </td>
                          </tr>

                          {isEditing && editForm ? (
                            <tr className="permissions-edit-row">
                              <td colSpan={5}>
                                <form
                                  className="permissions-edit-form"
                                  onSubmit={(event) =>
                                    void handleUpdate(event, assignment)
                                  }
                                >
                                  <div className="permissions-section-heading">
                                    <h4>Update assignment</h4>
                                    <p>
                                      Permission cannot be edited here. Revoke
                                      and grant again to change it.
                                    </p>
                                  </div>

                                  <label className="field-group permissions-enabled-field">
                                    <span>Enabled</span>
                                    <span className="permissions-checkbox-line">
                                      <input
                                        checked={editForm.enabled}
                                        disabled={isBusy}
                                        onChange={(event) =>
                                          setEditForm((current) =>
                                            current
                                              ? {
                                                  ...current,
                                                  enabled:
                                                    event.target.checked,
                                                }
                                              : current,
                                          )
                                        }
                                        type="checkbox"
                                      />
                                      Assignment enabled
                                    </span>
                                  </label>

                                  <label className="field-group">
                                    <span>Scope type</span>
                                    <select
                                      className="select-shell"
                                      disabled={isBusy}
                                      onChange={(event) =>
                                        setEditForm((current) =>
                                          current
                                            ? {
                                                ...current,
                                                scope_id:
                                                  event.target.value ===
                                                  "global"
                                                    ? "*"
                                                    : current.scope_id,
                                                scope_type:
                                                  event.target.value,
                                              }
                                            : current,
                                        )
                                      }
                                      value={editForm.scope_type}
                                    >
                                      {SCOPE_OPTIONS.map((scope) => (
                                        <option key={scope} value={scope}>
                                          {scopeLabel(scope)}
                                        </option>
                                      ))}
                                    </select>
                                  </label>

                                  <label className="field-group">
                                    <span>Scope ID</span>
                                    <span className="input-shell">
                                      <input
                                        disabled={
                                          isBusy ||
                                          editForm.scope_type === "global"
                                        }
                                        onChange={(event) =>
                                          setEditForm((current) =>
                                            current
                                              ? {
                                                  ...current,
                                                  scope_id:
                                                    event.target.value,
                                                }
                                              : current,
                                          )
                                        }
                                        type="text"
                                        value={
                                          editForm.scope_type === "global"
                                            ? "*"
                                            : editForm.scope_id
                                        }
                                      />
                                    </span>
                                  </label>

                                  <label className="field-group">
                                    <span>Expires at</span>
                                    <span className="input-shell">
                                      <input
                                        disabled={isBusy}
                                        onChange={(event) =>
                                          setEditForm((current) =>
                                            current
                                              ? {
                                                  ...current,
                                                  expires_at:
                                                    event.target.value,
                                                }
                                              : current,
                                          )
                                        }
                                        type="datetime-local"
                                        value={editForm.expires_at}
                                      />
                                    </span>
                                  </label>

                                  <label className="field-group permissions-reason-field">
                                    <span>Reason</span>
                                    <span className="textarea-shell">
                                      <textarea
                                        disabled={isBusy}
                                        maxLength={4000}
                                        onChange={(event) =>
                                          setEditForm((current) =>
                                            current
                                              ? {
                                                  ...current,
                                                  reason:
                                                    event.target.value,
                                                }
                                              : current,
                                          )
                                        }
                                        value={editForm.reason}
                                      />
                                    </span>
                                  </label>

                                  {needsUpdateConfirmation ? (
                                    <div className="permissions-risk-box" role="alert">
                                      <AlertTriangle
                                        aria-hidden="true"
                                        size={18}
                                      />
                                      <div>
                                        <strong>
                                          High-risk permission changes require
                                          confirmation.
                                        </strong>
                                        <label className="permissions-checkbox-line">
                                          <input
                                            checked={
                                              editForm.confirm_high_risk
                                            }
                                            disabled={isBusy}
                                            onChange={(event) =>
                                              setEditForm((current) =>
                                                current
                                                  ? {
                                                      ...current,
                                                      confirm_high_risk:
                                                        event.target.checked,
                                                    }
                                                  : current,
                                              )
                                            }
                                            type="checkbox"
                                          />
                                          Confirm high-risk update
                                        </label>
                                        <label className="field-group">
                                          <span>
                                            请输入 {HIGH_RISK_CONFIRMATION_TEXT}
                                          </span>
                                          <span className="input-shell">
                                            <input
                                              disabled={isBusy}
                                              onChange={(event) =>
                                                setEditForm((current) =>
                                                  current
                                                    ? {
                                                        ...current,
                                                        confirmation_text:
                                                          event.target.value,
                                                      }
                                                    : current,
                                                )
                                              }
                                              type="text"
                                              value={
                                                editForm.confirmation_text
                                              }
                                            />
                                          </span>
                                        </label>
                                      </div>
                                    </div>
                                  ) : null}

                                  <div className="users-inline-actions">
                                    <button
                                      className="primary-button"
                                      disabled={isBusy}
                                      type="submit"
                                    >
                                      {pendingAction ===
                                      `update-${assignment.id}` ? (
                                        <LoaderCircle
                                          className="spin"
                                          aria-hidden="true"
                                          size={17}
                                        />
                                      ) : (
                                        <Save aria-hidden="true" size={17} />
                                      )}
                                      Save assignment
                                    </button>
                                    <button
                                      className="secondary-button"
                                      disabled={isBusy}
                                      onClick={() => {
                                        setEditingAssignmentId(null);
                                        setEditForm(null);
                                      }}
                                      type="button"
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                </form>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </section>
  );
}
