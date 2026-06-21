import { apiRequest } from "@/lib/api";
import {
  normalizeModuleRegistryResponse,
  type ModuleRegistryResponse,
} from "@/lib/module-registry";

export const REVIEW_AUDIT_PAGE_LIMIT = 10;
export const REVIEW_AUDIT_EMPLOYEE_LIMIT = 100;
export const REVIEW_ORGANIZATION_CATALOG_LIMIT = 100;

export type ReviewAuditOrganization = {
  organization_id: string;
  organization_name: string;
  organization_type: string;
  employee_count: number;
  action_count: number;
  latest_action_at: string | null;
};

export type ReviewAuditEmployee = {
  user_id: number;
  employee_name: string;
  employee_role: string;
  job_title: string | null;
  action_count: number;
  latest_action_at: string | null;
};

export type ReviewAuditAction = {
  audit_id: string;
  organization_id: string;
  organization_name: string;
  user_id: number;
  employee_name: string;
  approval_module: string;
  operation_type: "同意" | "拒绝";
  status: "approved" | "rejected";
  rejection_reason: string | null;
  action_time: string;
  related_object_type: string;
  related_object: string;
  summary: string;
};

export type ReviewAuditListResponse<T> = {
  items: T[];
  count: number;
  limit: number;
  offset: number;
  degraded: boolean;
};

export type ReviewAuditFilters = {
  employeeId?: number;
  organizationId?: string;
  employee?: string;
  module?: string;
  startDate?: string;
  endDate?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function nullableString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeDateString(value: unknown) {
  return typeof value === "string" && value ? value : null;
}

function normalizeOrganization(value: unknown): ReviewAuditOrganization | null {
  if (!isRecord(value)) {
    return null;
  }
  const organizationId = stringValue(value.organization_id, stringValue(value.org_id));
  if (!organizationId) {
    return null;
  }
  return {
    action_count: numberValue(value.action_count),
    employee_count: numberValue(value.employee_count),
    latest_action_at: normalizeDateString(value.latest_action_at),
    organization_id: organizationId,
    organization_name: stringValue(
      value.organization_name,
      stringValue(value.org_name, organizationId),
    ),
    organization_type: stringValue(
      value.organization_type,
      stringValue(value.org_type, "组织"),
    ),
  };
}

function normalizeEmployee(value: unknown): ReviewAuditEmployee | null {
  if (!isRecord(value)) {
    return null;
  }
  const userId = numberValue(value.user_id, numberValue(value.id, 0));
  if (userId <= 0) {
    return null;
  }
  return {
    action_count: numberValue(value.action_count),
    employee_name: stringValue(
      value.employee_name,
      stringValue(value.username, `员工 ${userId}`),
    ),
    employee_role: stringValue(
      value.employee_role,
      stringValue(value.role, "员工"),
    ),
    job_title: nullableString(value.job_title),
    latest_action_at: normalizeDateString(value.latest_action_at),
    user_id: userId,
  };
}

function normalizeAction(value: unknown): ReviewAuditAction | null {
  if (!isRecord(value)) {
    return null;
  }
  const auditId = stringValue(value.audit_id);
  if (!auditId) {
    return null;
  }
  const status = value.status === "rejected" ? "rejected" : "approved";
  return {
    action_time: stringValue(value.action_time),
    approval_module: stringValue(value.approval_module, "审批"),
    audit_id: auditId,
    employee_name: stringValue(value.employee_name, "员工"),
    operation_type: status === "rejected" ? "拒绝" : "同意",
    organization_id: stringValue(value.organization_id),
    organization_name: stringValue(value.organization_name, "组织"),
    rejection_reason: nullableString(value.rejection_reason),
    related_object: stringValue(value.related_object, "审批记录"),
    related_object_type: stringValue(value.related_object_type, "审批"),
    status,
    summary: stringValue(value.summary, "审批记录已更新。"),
    user_id: numberValue(value.user_id),
  };
}

function normalizeListResponse<T>(
  value: unknown,
  normalizeItem: (item: unknown) => T | null,
): ReviewAuditListResponse<T> {
  const record = isRecord(value) ? value : {};
  const rawItems = Array.isArray(record.items) ? record.items : [];
  const items = rawItems
    .map(normalizeItem)
    .filter((item): item is T => item !== null);
  return {
    count: numberValue(record.count, items.length),
    degraded: booleanValue(record.degraded),
    items,
    limit: numberValue(record.limit, REVIEW_AUDIT_PAGE_LIMIT),
    offset: numberValue(record.offset),
  };
}

function appendFilters(params: URLSearchParams, filters: ReviewAuditFilters) {
  if (filters.organizationId) {
    params.set("organization_id", filters.organizationId);
  }
  if (filters.employee?.trim()) {
    params.set("employee", filters.employee.trim());
  }
  if (filters.employeeId && filters.employeeId > 0) {
    params.set("employee_id", String(filters.employeeId));
  }
  if (filters.module?.trim()) {
    params.set("review_module", filters.module.trim());
  }
  if (filters.startDate) {
    params.set("start_date", filters.startDate);
  }
  if (filters.endDate) {
    params.set("end_date", filters.endDate);
  }
}

function pageParams(
  offset: number,
  filters: ReviewAuditFilters,
  limit = REVIEW_AUDIT_PAGE_LIMIT,
) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendFilters(params, filters);
  return params;
}

export async function listReviewAuditOrganizations({
  filters,
  offset,
  signal,
}: {
  filters: ReviewAuditFilters;
  offset: number;
  signal?: AbortSignal;
}) {
  const params = pageParams(offset, filters);
  return normalizeListResponse(
    await apiRequest<unknown>(`/reviews/organizations?${params.toString()}`, {
      method: "GET",
      retryLimit: 0,
      signal,
    }),
    normalizeOrganization,
  );
}

export async function listReviewAuditModuleRegistry({
  signal,
  timeoutMs,
}: {
  signal?: AbortSignal;
  timeoutMs?: number;
} = {}): Promise<ModuleRegistryResponse> {
  return normalizeModuleRegistryResponse(
    await apiRequest<unknown>("/reviews/module-registry", {
      method: "GET",
      retryLimit: 0,
      signal,
      timeoutMs,
    }),
  );
}

export async function listReviewOrganizationCatalog({
  offset,
  signal,
}: {
  offset: number;
  signal?: AbortSignal;
}) {
  const params = new URLSearchParams({
    limit: String(REVIEW_ORGANIZATION_CATALOG_LIMIT),
    offset: String(Math.max(0, offset)),
  });
  return normalizeListResponse(
    await apiRequest<unknown>(`/organizations?${params.toString()}`, {
      method: "GET",
      retryLimit: 0,
      signal,
    }),
    normalizeOrganization,
  );
}

export async function listAllReviewOrganizationCatalog({
  signal,
}: {
  signal?: AbortSignal;
} = {}) {
  const items: ReviewAuditOrganization[] = [];
  let offset = 0;
  let lastResponse: ReviewAuditListResponse<ReviewAuditOrganization> | null = null;

  while (true) {
    const response = await listReviewOrganizationCatalog({ offset, signal });
    items.push(...response.items);
    lastResponse = response;

    if (response.items.length < REVIEW_ORGANIZATION_CATALOG_LIMIT) {
      break;
    }
    offset += REVIEW_ORGANIZATION_CATALOG_LIMIT;
  }

  return {
    count: items.length,
    degraded: lastResponse?.degraded ?? false,
    items,
    limit: REVIEW_ORGANIZATION_CATALOG_LIMIT,
    offset: 0,
  };
}

export async function listReviewOrganizationEmployees({
  employee,
  offset,
  organizationId,
  signal,
}: {
  employee?: string;
  offset: number;
  organizationId: string;
  signal?: AbortSignal;
}) {
  const params = new URLSearchParams({
    limit: String(REVIEW_AUDIT_EMPLOYEE_LIMIT),
    offset: String(Math.max(0, offset)),
    organization_id: organizationId,
  });
  if (employee?.trim()) {
    params.set("employee", employee.trim());
  }
  return normalizeListResponse(
    await apiRequest<unknown>(`/users?${params.toString()}`, {
      method: "GET",
      retryLimit: 0,
      signal,
    }),
    normalizeEmployee,
  );
}

export async function listReviewAuditEmployees({
  filters,
  offset,
  organizationId,
  signal,
}: {
  filters: ReviewAuditFilters;
  offset: number;
  organizationId: string;
  signal?: AbortSignal;
}) {
  const params = pageParams(offset, {
    ...filters,
    organizationId: undefined,
  }, REVIEW_AUDIT_EMPLOYEE_LIMIT);
  return normalizeListResponse(
    await apiRequest<unknown>(
      `/reviews/organizations/${encodeURIComponent(organizationId)}/users?${params.toString()}`,
      {
        method: "GET",
        retryLimit: 0,
        signal,
      },
    ),
    normalizeEmployee,
  );
}

export async function listReviewAuditActions({
  filters,
  offset,
  organizationId,
  signal,
  userId,
}: {
  filters: ReviewAuditFilters;
  offset: number;
  organizationId: string;
  signal?: AbortSignal;
  userId: number;
}) {
  const params = pageParams(offset, {
    ...filters,
    employee: undefined,
    organizationId: undefined,
  });
  return normalizeListResponse(
    await apiRequest<unknown>(
      `/reviews/organizations/${encodeURIComponent(organizationId)}/users/${userId}/actions?${params.toString()}`,
      {
        method: "GET",
        retryLimit: 0,
        signal,
      },
    ),
    normalizeAction,
  );
}
