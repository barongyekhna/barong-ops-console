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
const ORGANIZATION_PAGE_LIMIT = 10;

function messageFromError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "请重新登录后再操作。";
    }
    if (error.status === 403) {
      return "当前账号无权执行此操作。";
    }
    if (error.status >= 500) {
      return "加载失败，请稍后重试。";
    }
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
  return user.username;
}

function organizationName(organization: OrganizationRecord) {
  return organization.org_name.trim() || "未命名组织";
}

function organizationKey(organization: OrganizationRecord, index: number) {
  return organization.org_id || `${organization.org_name}-${index}`;
}

async function listOrganizations(offset: number) {
  const params = new URLSearchParams({
    limit: String(ORGANIZATION_PAGE_LIMIT),
    offset: String(Math.max(0, offset)),
  });
  return apiRequest<ListResponse<OrganizationRecord>>(
    `/organizations?${params.toString()}`,
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
          <h3 id="create-organization-title">创建组织</h3>
        </div>
        <Plus aria-hidden="true" size={18} />
      </div>

      <form className="product-form" onSubmit={onSubmit}>
        <label className="field-group">
          <span>组织名称</span>
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
          创建
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
  onPage,
  offset,
  total,
  organizations,
  superAdminError,
  superAdminLabelForOrganization,
}: {
  isLoading: boolean;
  listError: string;
  onRefresh: () => void;
  onPage: (offset: number) => void;
  offset: number;
  organizations: OrganizationRecord[];
  superAdminError: string;
  superAdminLabelForOrganization: (organization: OrganizationRecord) => string;
  total: number;
}) {
  return (
    <article className="ops-panel" aria-labelledby="organization-list-title">
      <div className="ops-panel-heading">
        <div>
          <h3 id="organization-list-title">组织列表</h3>
          <p>共 {total} 个组织，每页 {ORGANIZATION_PAGE_LIMIT} 条。</p>
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
          刷新
        </button>
      </div>

      {listError ? (
        <div className="ops-empty-state" role="alert">
          <strong>
            {organizations.length > 0
              ? "加载失败，请稍后重试"
              : "加载失败，请稍后重试"}
          </strong>
          <span>{listError || "加载失败，请稍后重试。"}</span>
          {organizations.length > 0 ? (
            <span>正在显示上一次成功加载的组织列表。</span>
          ) : null}
        </div>
      ) : null}

      {isLoading && organizations.length === 0 ? (
        <div className="list-state" aria-label="正在加载组织">
          正在加载组织
        </div>
      ) : null}

      {!isLoading && !listError && organizations.length === 0 ? (
        <div className="ops-empty-state" role="status">
          <strong>暂无数据</strong>
          <span>当前没有可显示的组织。</span>
        </div>
      ) : null}

      {organizations.length > 0 ? (
        <div className="users-table-scroll">
          <table className="users-table organization-table">
            <thead>
              <tr>
                <th scope="col">组织名称</th>
                <th scope="col">组织管理员</th>
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
      ) : null}

      {organizations.length > 0 ? (
        <div className="review-pager">
          <button
            className="secondary-button"
            disabled={isLoading || offset === 0}
            onClick={() => onPage(Math.max(0, offset - ORGANIZATION_PAGE_LIMIT))}
            type="button"
          >
            上一页
          </button>
          <span>{Math.floor(offset / ORGANIZATION_PAGE_LIMIT) + 1}</span>
          <button
            className="secondary-button"
            disabled={isLoading || offset + ORGANIZATION_PAGE_LIMIT >= total}
            onClick={() => onPage(offset + ORGANIZATION_PAGE_LIMIT)}
            type="button"
          >
            下一页
          </button>
        </div>
      ) : null}

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
  const [organizationCount, setOrganizationCount] = useState(0);
  const [organizationOffset, setOrganizationOffset] = useState(0);
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

      return ownerUserId ? "已指定负责人" : "未分配";
    },
    [superAdminsByIdentity, superAdminsByOrganization],
  );

  const loadOrganizations = useCallback(
    async ({
      offset = organizationOffset,
      showLoading = true,
    }: {
      offset?: number;
      showLoading?: boolean;
    } = {}) => {
      if (showLoading) {
        setIsListLoading(true);
      }
      setListError("");
      setSuperAdminError("");

      try {
        const organizationResult = await listOrganizations(offset);
        setOrganizations(organizationResult.items);
        setOrganizationCount(organizationResult.count);
        setOrganizationOffset(offset);
      } catch (error) {
        setListError(
          messageFromError(
            error,
            "加载失败，请稍后重试。",
          ),
        );
      }

      try {
        const superAdminResult = await listSuperAdminUsers();
        setSuperAdmins(superAdminResult.items);
      } catch (error) {
        setSuperAdminError(
          messageFromError(
            error,
            "组织管理员信息加载失败，请稍后重试。",
          ),
        );
      }

      if (showLoading) {
        setIsListLoading(false);
      }
    },
    [organizationOffset],
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
      setCreateError("请填写组织名称。");
      return;
    }

    if (!user?.id) {
      setCreateError("请重新登录后再创建组织。");
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
      setCreateNotice("组织已创建。");
      await loadOrganizations({ offset: organizationOffset, showLoading: false });
    } catch (error) {
      setCreateError(
        messageFromError(error, "组织创建失败，请稍后重试。"),
      );
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <section className="product-console" aria-label="组织管理">
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
        onPage={(offset) => void loadOrganizations({ offset })}
        offset={organizationOffset}
        organizations={organizations}
        superAdminError={superAdminError}
        superAdminLabelForOrganization={superAdminLabelForOrganization}
        total={organizationCount}
      />
    </section>
  );
}
