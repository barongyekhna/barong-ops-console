"use client";

import { LoaderCircle, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest } from "@/lib/api";

type AuthContextResponse = {
  user_id: number;
  org_id: string | null;
  role: string | null;
  module_scope: string[];
  context_available: boolean;
  resolution_source: string | null;
};

type OrgRecord = {
  org_id: string;
  org_name: string;
  org_type: string;
  status: string;
  owner_user_id: string;
  created_at?: string;
  updated_at?: string;
};

type OrgMember = {
  membership_id: string;
  user_id: string;
  org_id: string;
  role: string;
  status: string;
  joined_at: string;
};

function messageFromError(error: unknown, fallback: string) {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || fallback;
  }
  return fallback;
}

export function OrganizationProductView() {
  const { user } = useAuth();
  const [context, setContext] = useState<AuthContextResponse | null>(null);
  const [contextError, setContextError] = useState("");
  const [isContextLoading, setIsContextLoading] = useState(true);
  const [orgId, setOrgId] = useState("");
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [membersError, setMembersError] = useState("");
  const [isMembersLoading, setIsMembersLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [createdOrg, setCreatedOrg] = useState<OrgRecord | null>(null);
  const [createForm, setCreateForm] = useState({
    org_name: "",
    org_type: "store",
    owner_user_id: user?.id ? String(user.id) : "",
  });
  const [lifecycleForm, setLifecycleForm] = useState({
    org_name: "",
    org_type: "",
  });
  const [memberForm, setMemberForm] = useState({
    role: "member",
    user_id: "",
  });

  const loadContext = useCallback(async () => {
    setIsContextLoading(true);
    setContextError("");
    try {
      const result = await apiRequest<AuthContextResponse>("/auth/context", {
        method: "GET",
      });
      setContext(result);
      if (result.org_id) {
        setOrgId(result.org_id);
      }
    } catch (error) {
      setContext(null);
      setContextError(
        messageFromError(error, "Organization context is unavailable."),
      );
    } finally {
      setIsContextLoading(false);
    }
  }, []);

  const loadMembers = useCallback(
    async (targetOrgId = orgId) => {
      const trimmedOrgId = targetOrgId.trim();
      if (!trimmedOrgId) {
        setMembers([]);
        setMembersError("Enter an organization ID to load members.");
        return;
      }

      setIsMembersLoading(true);
      setMembersError("");
      try {
        setMembers(
          await apiRequest<OrgMember[]>(`/org/${trimmedOrgId}/members`, {
            method: "GET",
          }),
        );
      } catch (error) {
        setMembers([]);
        setMembersError(messageFromError(error, "Members are unavailable."));
      } finally {
        setIsMembersLoading(false);
      }
    },
    [orgId],
  );

  useEffect(() => {
    void loadContext();
  }, [loadContext]);

  useEffect(() => {
    if (context?.org_id) {
      void loadMembers(context.org_id);
    }
  }, [context?.org_id, loadMembers]);

  function clearActionState() {
    setNotice("");
    setActionError("");
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearActionState();
    setIsBusy(true);
    try {
      const org = await apiRequest<OrgRecord>("/org/create", {
        body: {
          metadata: {
            country: "",
            custom: {},
            industry: "",
            settings: {
              allow_ai: false,
              allow_n8n: false,
              data_retention_days: 365,
            },
            timezone: "UTC",
          },
          ...createForm,
        },
        method: "POST",
      });
      setCreatedOrg(org);
      setOrgId(org.org_id);
      setNotice(`Created organization ${org.org_id}.`);
      await loadMembers(org.org_id);
    } catch (error) {
      setActionError(messageFromError(error, "Organization could not be created."));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleLifecycle(action: "update" | "activate" | "suspend" | "delete") {
    const targetOrgId = orgId.trim();
    clearActionState();
    if (!targetOrgId) {
      setActionError("Enter an organization ID first.");
      return;
    }

    setIsBusy(true);
    try {
      let org: OrgRecord;
      if (action === "update") {
        const body: Record<string, string> = {};
        if (lifecycleForm.org_name.trim()) {
          body.org_name = lifecycleForm.org_name.trim();
        }
        if (lifecycleForm.org_type.trim()) {
          body.org_type = lifecycleForm.org_type.trim();
        }
        org = await apiRequest<OrgRecord>(`/org/${targetOrgId}`, {
          body,
          method: "PATCH",
        });
      } else if (action === "delete") {
        org = await apiRequest<OrgRecord>(`/org/${targetOrgId}`, {
          method: "DELETE",
        });
      } else {
        org = await apiRequest<OrgRecord>(`/org/${targetOrgId}/${action}`, {
          method: "POST",
        });
      }
      setCreatedOrg(org);
      setNotice(`${action} completed for ${org.org_id}.`);
      await loadMembers(targetOrgId);
    } catch (error) {
      setActionError(messageFromError(error, "Organization action failed."));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleMember(action: "add" | "remove") {
    const targetOrgId = orgId.trim();
    clearActionState();
    if (!targetOrgId || !memberForm.user_id.trim()) {
      setActionError("Enter an organization ID and user ID.");
      return;
    }

    setIsBusy(true);
    try {
      await apiRequest<OrgMember>(`/org/${targetOrgId}/members/${action}`, {
        body:
          action === "add"
            ? {
                role: memberForm.role,
                user_id: memberForm.user_id.trim(),
              }
            : {
                user_id: memberForm.user_id.trim(),
              },
        method: "POST",
      });
      setNotice(`Member ${action} completed.`);
      await loadMembers(targetOrgId);
    } catch (error) {
      setActionError(messageFromError(error, "Member action failed."));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="product-console" aria-label="Organizations">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Users & Organizations</span>
          <h2>Organizations</h2>
          <p>
            Organization context, lifecycle operations, and membership management
            backed by the existing org APIs.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isContextLoading}
          onClick={() => void loadContext()}
          type="button"
        >
          {isContextLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Context</span>
          <strong>{context?.context_available ? "available" : "unknown"}</strong>
        </div>
        <div>
          <span>Active org</span>
          <strong>{context?.org_id ?? "Not set"}</strong>
        </div>
        <div>
          <span>Org role</span>
          <strong>{context?.role ?? "Not set"}</strong>
        </div>
        <div>
          <span>Members</span>
          <strong>{members.length}</strong>
        </div>
      </div>

      {contextError ? <p className="ops-warning">{contextError}</p> : null}
      {notice ? <p className="ops-warning product-notice">{notice}</p> : null}
      {actionError ? <p className="ops-warning">{actionError}</p> : null}

      <div className="product-console-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Organization detail</h3>
              <p>/auth/context and latest lifecycle response</p>
            </div>
            <span className="ops-source">detail</span>
          </div>
          <dl className="ops-readiness-list product-detail-list">
            <div>
              <dt>User ID</dt>
              <dd>{context?.user_id ?? user?.id ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Organization ID</dt>
              <dd>{createdOrg?.org_id ?? context?.org_id ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Name</dt>
              <dd>{createdOrg?.org_name ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{createdOrg?.status ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Module scope</dt>
              <dd>{context?.module_scope.join(", ") || "Not set"}</dd>
            </div>
            <div>
              <dt>Resolution</dt>
              <dd>{context?.resolution_source ?? "Not set"}</dd>
            </div>
          </dl>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Members</h3>
              <p>/org/:org_id/members</p>
            </div>
            <button
              className="secondary-button"
              disabled={isMembersLoading}
              onClick={() => void loadMembers()}
              type="button"
            >
              {isMembersLoading ? (
                <LoaderCircle aria-hidden="true" className="spin" size={15} />
              ) : (
                <RotateCcw aria-hidden="true" size={15} />
              )}
              Load
            </button>
          </div>
          <label className="field-group">
            <span>Organization ID</span>
            <span className="input-shell">
              <input
                onChange={(event) => setOrgId(event.target.value)}
                placeholder="org_..."
                value={orgId}
              />
            </span>
          </label>
          {membersError ? <p className="ops-warning">{membersError}</p> : null}
          {members.length > 0 ? (
            <ol className="ops-record-list">
              {members.map((member) => (
                <li key={member.membership_id}>
                  <span>{member.role}</span>
                  <strong>{member.user_id}</strong>
                  <small>
                    {member.status} / {member.membership_id}
                  </small>
                </li>
              ))}
            </ol>
          ) : (
            <div className="ops-empty-state">
              <strong>No members loaded.</strong>
              <span>Enter an org ID and load members.</span>
            </div>
          )}
        </article>
      </div>

      <section className="ops-dashboard-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Create organization</h3>
              <p>/org/create</p>
            </div>
            <Plus aria-hidden="true" size={18} />
          </div>
          <form className="product-form" onSubmit={(event) => void handleCreate(event)}>
            <label className="field-group">
              <span>Name</span>
              <span className="input-shell">
                <input
                  onChange={(event) =>
                    setCreateForm((current) => ({
                      ...current,
                      org_name: event.target.value,
                    }))
                  }
                  required
                  value={createForm.org_name}
                />
              </span>
            </label>
            <label className="field-group">
              <span>Type</span>
              <select
                className="select-shell"
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    org_type: event.target.value,
                  }))
                }
                value={createForm.org_type}
              >
                <option value="store">Store</option>
                <option value="factory">Factory</option>
                <option value="warehouse">Warehouse</option>
              </select>
            </label>
            <label className="field-group">
              <span>Owner user ID</span>
              <span className="input-shell">
                <input
                  onChange={(event) =>
                    setCreateForm((current) => ({
                      ...current,
                      owner_user_id: event.target.value,
                    }))
                  }
                  required
                  value={createForm.owner_user_id}
                />
              </span>
            </label>
            <button className="primary-button" disabled={isBusy} type="submit">
              <Save aria-hidden="true" size={17} />
              Create
            </button>
          </form>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Lifecycle actions</h3>
              <p>/org/:org_id update, activate, suspend, delete</p>
            </div>
            <span className="ops-source">owner</span>
          </div>
          <div className="product-form">
            <label className="field-group">
              <span>New name</span>
              <span className="input-shell">
                <input
                  onChange={(event) =>
                    setLifecycleForm((current) => ({
                      ...current,
                      org_name: event.target.value,
                    }))
                  }
                  value={lifecycleForm.org_name}
                />
              </span>
            </label>
            <label className="field-group">
              <span>New type</span>
              <select
                className="select-shell"
                onChange={(event) =>
                  setLifecycleForm((current) => ({
                    ...current,
                    org_type: event.target.value,
                  }))
                }
                value={lifecycleForm.org_type}
              >
                <option value="">No change</option>
                <option value="store">Store</option>
                <option value="factory">Factory</option>
                <option value="warehouse">Warehouse</option>
              </select>
            </label>
            <div className="product-button-row">
              <button
                className="secondary-button"
                disabled={isBusy}
                onClick={() => void handleLifecycle("update")}
                type="button"
              >
                Update
              </button>
              <button
                className="secondary-button"
                disabled={isBusy}
                onClick={() => void handleLifecycle("activate")}
                type="button"
              >
                Activate
              </button>
              <button
                className="secondary-button"
                disabled={isBusy}
                onClick={() => void handleLifecycle("suspend")}
                type="button"
              >
                Suspend
              </button>
              <button
                className="danger-button"
                disabled={isBusy}
                onClick={() => void handleLifecycle("delete")}
                type="button"
              >
                <Trash2 aria-hidden="true" size={15} />
                Delete
              </button>
            </div>
          </div>
        </article>

        <article className="ops-panel ops-panel-wide">
          <div className="ops-panel-heading">
            <div>
              <h3>Member actions</h3>
              <p>/org/:org_id/members/add and /org/:org_id/members/remove</p>
            </div>
            <span className="ops-source">membership</span>
          </div>
          <div className="users-form-grid">
            <label className="field-group">
              <span>User ID</span>
              <span className="input-shell">
                <input
                  onChange={(event) =>
                    setMemberForm((current) => ({
                      ...current,
                      user_id: event.target.value,
                    }))
                  }
                  value={memberForm.user_id}
                />
              </span>
            </label>
            <label className="field-group">
              <span>Role</span>
              <select
                className="select-shell"
                onChange={(event) =>
                  setMemberForm((current) => ({
                    ...current,
                    role: event.target.value,
                  }))
                }
                value={memberForm.role}
              >
                <option value="member">Member</option>
                <option value="admin">Admin</option>
                <option value="owner">Owner</option>
              </select>
            </label>
            <div className="product-button-row product-button-row-bottom">
              <button
                className="primary-button"
                disabled={isBusy}
                onClick={() => void handleMember("add")}
                type="button"
              >
                Add member
              </button>
              <button
                className="danger-button"
                disabled={isBusy}
                onClick={() => void handleMember("remove")}
                type="button"
              >
                Remove member
              </button>
            </div>
          </div>
        </article>
      </section>
    </section>
  );
}
