"use client";

import { LoaderCircle, Plus, RotateCcw } from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest } from "@/lib/api";
import {
  listSuperAdminUsers,
  type ManagedUser,
} from "@/lib/users-api";

type ListResponse<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
};

type OrganizationRecord = {
  org_id: string;
  org_name: string;
  owner_user_id: string | number | null;
};

const CREATE_ORGANIZATION_API_COMPAT_ORG_TYPE = "store";

function messageFromError(error: unknown, fallback: string) {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || fallback;
  }
  return fallback;
}

function normalizeIdentifier(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function formatManagedUser(user: ManagedUser) {
  return `${user.username} (#${user.id})`;
}

function organizationName(organization: OrganizationRecord) {
  return organization.org_name.trim() || "Unnamed organization";
}

function organizationKey(organization: OrganizationRecord, index: number) {
  return organization.org_id || `${organization.org_name}-${index}`;
}

async function listOrganizations() {
  return apiRequest<ListResponse<OrganizationRecord>>(
    "/organizations?limit=100&offset=0",
    {
      method: "GET",
    },
  );
}

function CreateOrganizationSection({
  createError,
  createName,
  createNotice,
  isCreating,
  onCreateNameChange,
  onSubmit,
}: {
  createError: string;
  createName: string;
  createNotice: string;
  isCreating: boolean;
  onCreateNameChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <article className="ops-panel" aria-labelledby="create-organization-title">
      <div className="ops-panel-heading">
        <div>
          <h3 id="create-organization-title">Create Organization</h3>
        </div>
        <Plus aria-hidden="true" size={18} />
      </div>

      <form className="product-form" onSubmit={onSubmit}>
        <label className="field-group">
          <span>Organization name</span>
          <span className="input-shell">
            <input
              autoComplete="organization"
              onChange={(event) => onCreateNameChange(event.target.value)}
              required
              value={createName}
            />
          </span>
        </label>

        <button className="primary-button" disabled={isCreating} type="submit">
          {isCreating ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          Create
        </button>
      </form>

      {createError ? (
        <p className="ops-warning" role="alert">
          {createError}
        </p>
      ) : null}
      {createNotice ? (
        <p className="ops-warning product-notice" role="status">
          {createNotice}
        </p>
      ) : null}
    </article>
  );
}

function OrganizationListSection({
  isLoading,
  listError,
  onRefresh,
  organizations,
  superAdminError,
  superAdminLabelForOrganization,
}: {
  isLoading: boolean;
  listError: string;
  onRefresh: () => void;
  organizations: OrganizationRecord[];
  superAdminError: string;
  superAdminLabelForOrganization: (organization: OrganizationRecord) => string;
}) {
  return (
    <article className="ops-panel" aria-labelledby="organization-list-title">
      <div className="ops-panel-heading">
        <div>
          <h3 id="organization-list-title">Organization List</h3>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={onRefresh}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <RotateCcw aria-hidden="true" size={15} />
          )}
          Refresh
        </button>
      </div>

      {listError ? (
        <div className="ops-empty-state" role="alert">
          <strong>Organization list is unavailable.</strong>
          <span>{listError}</span>
        </div>
      ) : isLoading ? (
        <div className="list-state" aria-label="Loading organizations">
          Loading organizations.
        </div>
      ) : organizations.length === 0 ? (
        <div className="ops-empty-state" role="status">
          <strong>No organizations found.</strong>
          <span>No organization records are available.</span>
        </div>
      ) : (
        <div className="users-table-scroll">
          <table className="users-table organization-table">
            <thead>
              <tr>
                <th scope="col">Organization name</th>
                <th scope="col">Super admin</th>
              </tr>
            </thead>
            <tbody>
              {organizations.map((organization, index) => (
                <tr key={organizationKey(organization, index)}>
                  <td>
                    <strong>{organizationName(organization)}</strong>
                  </td>
                  <td>{superAdminLabelForOrganization(organization)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {superAdminError && !listError ? (
        <p className="ops-warning" role="status">
          {superAdminError}
        </p>
      ) : null}
    </article>
  );
}

export function OrganizationProductView() {
  const { isOwner, user } = useAuth();
  const [organizations, setOrganizations] = useState<OrganizationRecord[]>([]);
  const [superAdmins, setSuperAdmins] = useState<ManagedUser[]>([]);
  const [isListLoading, setIsListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [superAdminError, setSuperAdminError] = useState("");
  const [createName, setCreateName] = useState("");
  const [createError, setCreateError] = useState("");
  const [createNotice, setCreateNotice] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const superAdminsByOrganization = useMemo(() => {
    const index = new Map<string, ManagedUser[]>();

    for (const superAdmin of superAdmins) {
      const organizationId = normalizeIdentifier(superAdmin.organization_id);
      if (!organizationId) {
        continue;
      }

      const current = index.get(organizationId) ?? [];
      current.push(superAdmin);
      index.set(organizationId, current);
    }

    return index;
  }, [superAdmins]);

  const superAdminsByIdentity = useMemo(() => {
    const index = new Map<string, ManagedUser>();

    for (const superAdmin of superAdmins) {
      index.set(String(superAdmin.id), superAdmin);
      index.set(superAdmin.username, superAdmin);
    }

    return index;
  }, [superAdmins]);

  const superAdminLabelForOrganization = useCallback(
    (organization: OrganizationRecord) => {
      const assignedSuperAdmins =
        superAdminsByOrganization.get(organization.org_id) ?? [];
      if (assignedSuperAdmins.length > 0) {
        return assignedSuperAdmins.map(formatManagedUser).join(", ");
      }

      const ownerUserId = normalizeIdentifier(organization.owner_user_id);
      const ownerMatchedSuperAdmin = superAdminsByIdentity.get(ownerUserId);
      if (ownerMatchedSuperAdmin) {
        return formatManagedUser(ownerMatchedSuperAdmin);
      }

      return ownerUserId ? `User ${ownerUserId}` : "Not assigned";
    },
    [superAdminsByIdentity, superAdminsByOrganization],
  );

  const loadOrganizations = useCallback(
    async ({ showLoading = true }: { showLoading?: boolean } = {}) => {
      if (showLoading) {
        setIsListLoading(true);
      }
      setListError("");
      setSuperAdminError("");

      const [organizationResult, superAdminResult] =
        await Promise.allSettled([
          listOrganizations(),
          listSuperAdminUsers(),
        ]);

      if (organizationResult.status === "fulfilled") {
        setOrganizations(organizationResult.value.items);
      } else {
        setOrganizations([]);
        setListError(
          messageFromError(
            organizationResult.reason,
            "Organizations could not be loaded.",
          ),
        );
      }

      if (superAdminResult.status === "fulfilled") {
        setSuperAdmins(superAdminResult.value.items);
      } else {
        setSuperAdmins([]);
        setSuperAdminError(
          messageFromError(
            superAdminResult.reason,
            "Super admin names could not be loaded; showing organization owner IDs.",
          ),
        );
      }

      if (showLoading) {
        setIsListLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadOrganizations();
  }, [loadOrganizations]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError("");
    setCreateNotice("");

    const name = createName.trim();
    if (!name) {
      setCreateError("Organization name is required.");
      return;
    }

    if (!user?.id) {
      setCreateError("Sign in again before creating an organization.");
      return;
    }

    setIsCreating(true);
    try {
      await apiRequest<OrganizationRecord>("/org/create", {
        body: {
          org_name: name,
          org_type: CREATE_ORGANIZATION_API_COMPAT_ORG_TYPE,
          owner_user_id: String(user.id),
        },
        method: "POST",
      });
      setCreateName("");
      setCreateNotice("Organization created.");
      await loadOrganizations({ showLoading: false });
    } catch (error) {
      setCreateError(
        messageFromError(error, "Organization could not be created."),
      );
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <section className="product-console" aria-label="Organizations">
      {isOwner ? (
        <CreateOrganizationSection
          createError={createError}
          createName={createName}
          createNotice={createNotice}
          isCreating={isCreating}
          onCreateNameChange={setCreateName}
          onSubmit={(event) => void handleCreate(event)}
        />
      ) : null}

      <OrganizationListSection
        isLoading={isListLoading}
        listError={listError}
        onRefresh={() => void loadOrganizations()}
        organizations={organizations}
        superAdminError={superAdminError}
        superAdminLabelForOrganization={superAdminLabelForOrganization}
      />
    </section>
  );
}
