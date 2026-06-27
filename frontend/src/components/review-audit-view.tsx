"use client";

import {
  Building2,
  CheckCircle2,
  RotateCcw,
  Search,
  UserRound,
  XCircle,
} from "lucide-react";
import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import {
  ApiError,
  ApiRequestAbortedError,
  isApiAbortError,
} from "@/lib/api";
import {
  listAllReviewOrganizationCatalog,
  listReviewAuditActions,
  listReviewAuditEmployees,
  listReviewAuditModuleRegistry,
  listReviewAuditOrganizations,
  REVIEW_AUDIT_PAGE_LIMIT,
  type ReviewAuditAction,
  type ReviewAuditEmployee,
  type ReviewAuditFilters,
  type ReviewAuditListResponse,
  type ReviewAuditOrganization,
} from "@/lib/review-audit";

const EMPTY_ORGANIZATIONS: ReviewAuditListResponse<ReviewAuditOrganization> = {
  count: 0,
  degraded: false,
  items: [],
  limit: REVIEW_AUDIT_PAGE_LIMIT,
  offset: 0,
};
const EMPTY_EMPLOYEES: ReviewAuditListResponse<ReviewAuditEmployee> = {
  count: 0,
  degraded: false,
  items: [],
  limit: 100,
  offset: 0,
};
const EMPTY_ACTIONS: ReviewAuditListResponse<ReviewAuditAction> = {
  count: 0,
  degraded: false,
  items: [],
  limit: REVIEW_AUDIT_PAGE_LIMIT,
  offset: 0,
};

type ModuleOption = {
  label: string;
  value: string;
};

const MODULE_LABELS: Record<string, string> = {
  Agents: "自动化助手",
  "Approval Audit": "审批审计",
  Dashboard: "控制台",
  Errors: "异常记录",
  "Foundation Demo": "内部演示",
  "Memory Events": "运行记录",
  Modules: "功能区",
  "n8n Test Bridge": "外部流程接入",
  "Operation Logs": "操作记录",
  "Permission Management": "权限管理",
  Products: "业务功能",
  "User Management": "用户管理",
  "admin.agents": "自动化助手",
  "admin.modules": "功能区",
  "admin.organizations": "组织管理",
  "admin.permissions": "权限管理",
  "admin.settings": "设置",
  "admin.users": "用户管理",
  "business.approvals": "审批",
  "business.reviews": "审批审计",
  "core.dashboard": "控制台",
  "system.errors": "异常记录",
  "system.memory_events": "运行记录",
  "system.operation_logs": "操作记录",
};

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "暂无时间";
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return "暂无时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}

function roleLabel(role: string) {
  const normalized = role.trim().toLowerCase();
  if (normalized === "owner") {
    return "owner";
  }
  if (normalized === "super_admin" || normalized === "admin") {
    return "管理员";
  }
  if (normalized === "reviewer") {
    return "审核员";
  }
  if (normalized === "operator") {
    return "操作员";
  }
  if (normalized === "viewer") {
    return "查看员";
  }
  return "员工";
}

function moduleLabel(value: string) {
  return MODULE_LABELS[value] ?? "审批";
}

function canUseReviewAudit(role: string | null | undefined) {
  return role === "owner" || role === "super_admin";
}

function reviewErrorText(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "";
    }
    if (error.status === 403) {
      return "当前账号无权查看审批审计。";
    }
    if (error.status >= 500) {
      return "";
    }
  }
  return fallback;
}

function employeeMatchesSearch(employee: ReviewAuditEmployee, search: string) {
  const query = search.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return (
    employee.employee_name.toLowerCase().includes(query) ||
    employee.employee_role.toLowerCase().includes(query) ||
    (employee.job_title ?? "").toLowerCase().includes(query)
  );
}

function ReviewLoadingState({ label }: { label: string }) {
  return (
    <div className="review-empty" role="status">
      <strong>{label}</strong>
      <div className="skeleton-stack" aria-hidden="true">
        <span className="skeleton-line medium" />
        <span className="skeleton-line" />
        <span className="skeleton-line short" />
      </div>
    </div>
  );
}

function PagingControls({
  disabled,
  hasNext,
  offset,
  onPage,
}: {
  disabled: boolean;
  hasNext: boolean;
  offset: number;
  onPage: (offset: number) => void;
}) {
  return (
    <div className="review-pager">
      <button
        className="secondary-button"
        disabled={disabled || offset === 0}
        onClick={() => onPage(Math.max(0, offset - REVIEW_AUDIT_PAGE_LIMIT))}
        type="button"
      >
        上一页
      </button>
      <span>{Math.floor(offset / REVIEW_AUDIT_PAGE_LIMIT) + 1}</span>
      <button
        className="secondary-button"
        disabled={disabled || !hasNext}
        onClick={() => onPage(offset + REVIEW_AUDIT_PAGE_LIMIT)}
        type="button"
      >
        下一页
      </button>
    </div>
  );
}

function ActionTimeline({
  actions,
}: {
  actions: ReviewAuditAction[];
}) {
  return (
    <ol className="review-timeline">
      {actions.map((action) => (
        <li className={`review-timeline-item ${action.status}`} key={action.audit_id}>
          <span className="review-timeline-marker">
            {action.status === "approved" ? (
              <CheckCircle2 aria-hidden="true" size={17} />
            ) : (
              <XCircle aria-hidden="true" size={17} />
            )}
          </span>
          <article className="review-action-card">
            <div className="review-action-top">
              <div>
                <strong>{moduleLabel(action.approval_module)}</strong>
                <span>
                  {action.organization_name} · {action.employee_name}
                </span>
              </div>
              <span className={`review-status ${action.status}`}>
                {action.operation_type}
              </span>
            </div>
            <p>{action.summary}</p>
            {action.rejection_reason ? (
              <p className="review-reason">拒绝原因：{action.rejection_reason}</p>
            ) : null}
            <time>{formatDate(action.action_time)}</time>
          </article>
        </li>
      ))}
    </ol>
  );
}

export function ReviewAuditView() {
  const { status, user } = useAuth();
  const isOwner = user?.role === "owner";
  const [draftFilters, setDraftFilters] = useState<ReviewAuditFilters>({});
  const [filters, setFilters] = useState<ReviewAuditFilters>({});
  const [filterMode, setFilterMode] = useState(false);
  const [organizations, setOrganizations] = useState(EMPTY_ORGANIZATIONS);
  const [organizationCatalog, setOrganizationCatalog] =
    useState(EMPTY_ORGANIZATIONS);
  const [employees, setEmployees] = useState(EMPTY_EMPLOYEES);
  const [filterEmployees, setFilterEmployees] = useState(EMPTY_EMPLOYEES);
  const [actions, setActions] = useState(EMPTY_ACTIONS);
  const [filteredActions, setFilteredActions] = useState(EMPTY_ACTIONS);
  const [moduleOptions, setModuleOptions] = useState<ModuleOption[]>([]);
  const [organizationOffset, setOrganizationOffset] = useState(0);
  const [filterEmployeeOffset, setFilterEmployeeOffset] = useState(0);
  const [actionOffset, setActionOffset] = useState(0);
  const [filteredActionOffset, setFilteredActionOffset] = useState(0);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [selectedFilterUserId, setSelectedFilterUserId] = useState<number | null>(null);
  const [detailEmployeeSearch, setDetailEmployeeSearch] = useState("");
  const [organizationLoading, setOrganizationLoading] = useState(true);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [employeeLoading, setEmployeeLoading] = useState(false);
  const [filterEmployeeLoading, setFilterEmployeeLoading] = useState(false);
  const [moduleLoading, setModuleLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [filteredActionLoading, setFilteredActionLoading] = useState(false);
  const [organizationError, setOrganizationError] = useState("");
  const [employeeError, setEmployeeError] = useState("");
  const [filterEmployeeError, setFilterEmployeeError] = useState("");
  const [moduleError, setModuleError] = useState("");
  const [actionError, setActionError] = useState("");
  const [filterError, setFilterError] = useState("");
  const organizationAbortRef = useRef<AbortController | null>(null);
  const catalogAbortRef = useRef<AbortController | null>(null);
  const employeeAbortRef = useRef<AbortController | null>(null);
  const filterEmployeeAbortRef = useRef<AbortController | null>(null);
  const actionAbortRef = useRef<AbortController | null>(null);
  const filteredActionAbortRef = useRef<AbortController | null>(null);

  const canUse = canUseReviewAudit(user?.role);
  const selectedOrganization = useMemo(
    () =>
      organizations.items.find(
        (item) => item.organization_id === selectedOrganizationId,
      ) ??
      organizationCatalog.items.find(
        (item) => item.organization_id === selectedOrganizationId,
      ) ??
      null,
    [organizationCatalog.items, organizations.items, selectedOrganizationId],
  );
  const selectedEmployee = useMemo(
    () => employees.items.find((item) => item.user_id === selectedUserId) ?? null,
    [employees.items, selectedUserId],
  );
  const employeeOrganizationId = useMemo(() => {
    if (isOwner) {
      return draftFilters.organizationId || selectedOrganizationId;
    }
    return (
      selectedOrganizationId ||
      organizations.items[0]?.organization_id ||
      user?.organization_id ||
      ""
    );
  }, [
    draftFilters.organizationId,
    isOwner,
    organizations.items,
    selectedOrganizationId,
    user?.organization_id,
  ]);
  const filteredEmployees = useMemo(() => {
    const search = filterMode ? (draftFilters.employee ?? "") : detailEmployeeSearch;
    return employees.items.filter((employee) =>
      employeeMatchesSearch(employee, search),
    );
  }, [detailEmployeeSearch, draftFilters.employee, employees.items, filterMode]);

  const loadOrganizations = useCallback(async (offset: number) => {
    const previous = organizationAbortRef.current;
    if (previous && !previous.signal.aborted) {
      previous.abort(new ApiRequestAbortedError("组织列表请求已替换。"));
    }
    const controller = new AbortController();
    organizationAbortRef.current = controller;
    setOrganizationLoading(true);
    setOrganizationError("");
    try {
      const data = await listReviewAuditOrganizations({
        filters: {},
        offset,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setOrganizations(data);
        setOrganizationOffset(offset);
        if (!isOwner && data.items[0] && !selectedOrganizationId) {
          setSelectedOrganizationId(data.items[0].organization_id);
        }
      }
    } catch (error) {
      if (isApiAbortError(error)) {
        return;
      }
      setOrganizationError(reviewErrorText(error, "组织审批审计暂时不可用。"));
    } finally {
      if (organizationAbortRef.current === controller) {
        organizationAbortRef.current = null;
        setOrganizationLoading(false);
      }
    }
  }, [isOwner, selectedOrganizationId]);

  const loadOrganizationCatalog = useCallback(async () => {
    const previous = catalogAbortRef.current;
    if (previous && !previous.signal.aborted) {
      previous.abort(new ApiRequestAbortedError("组织筛选列表请求已替换。"));
    }
    const controller = new AbortController();
    catalogAbortRef.current = controller;
    setCatalogLoading(true);
    try {
      const data = await listAllReviewOrganizationCatalog({
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setOrganizationCatalog(data);
      }
    } catch (error) {
      if (!isApiAbortError(error)) {
        setOrganizationCatalog(EMPTY_ORGANIZATIONS);
      }
    } finally {
      if (catalogAbortRef.current === controller) {
        catalogAbortRef.current = null;
        setCatalogLoading(false);
      }
    }
  }, []);

  const loadEmployees = useCallback(async (organizationId: string) => {
    if (!organizationId) {
      setEmployees(EMPTY_EMPLOYEES);
      return;
    }
    const previous = employeeAbortRef.current;
    if (previous && !previous.signal.aborted) {
      previous.abort(new ApiRequestAbortedError("员工列表请求已替换。"));
    }
    const controller = new AbortController();
    employeeAbortRef.current = controller;
    setEmployeeLoading(true);
    setEmployeeError("");
    try {
      const data = await listReviewAuditEmployees({
        filters: {
          employee: detailEmployeeSearch,
        },
        offset: 0,
        organizationId,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setEmployees(data);
        if (
          selectedUserId !== null &&
          !data.items.some((item) => item.user_id === selectedUserId)
        ) {
          setSelectedUserId(null);
          setActions(EMPTY_ACTIONS);
        }
      }
    } catch (error) {
      if (isApiAbortError(error)) {
        return;
      }
      setEmployees(EMPTY_EMPLOYEES);
        setEmployeeError(reviewErrorText(error, "员工列表暂时不可用。"));
    } finally {
      if (employeeAbortRef.current === controller) {
        employeeAbortRef.current = null;
        setEmployeeLoading(false);
      }
    }
  }, [detailEmployeeSearch, selectedUserId]);

  const loadModules = useCallback(async () => {
    setModuleLoading(true);
    setModuleError("");
    try {
      const result = await listReviewAuditModuleRegistry({ timeoutMs: 5_000 });
      setModuleOptions(
        result.items
          .map((module) => ({
            label:
              MODULE_LABELS[module.module_key] ??
              MODULE_LABELS[module.display_name] ??
              "业务功能",
            value: module.module_key,
          }))
          .sort((left, right) => left.label.localeCompare(right.label, "zh-CN")),
      );
    } catch (error) {
      setModuleOptions([]);
      setModuleError(reviewErrorText(error, "模块列表暂时不可用。"));
    } finally {
      setModuleLoading(false);
    }
  }, []);

  const loadActions = useCallback(
    async (organizationId: string, userId: number, offset: number) => {
      const previous = actionAbortRef.current;
      if (previous && !previous.signal.aborted) {
        previous.abort(new ApiRequestAbortedError("审批记录请求已替换。"));
      }
      const controller = new AbortController();
      actionAbortRef.current = controller;
      setActionLoading(true);
      setActionError("");
      try {
        const data = await listReviewAuditActions({
          filters: {},
          offset,
          organizationId,
          signal: controller.signal,
          userId,
        });
        if (!controller.signal.aborted) {
          setActions(data);
          setActionOffset(offset);
        }
      } catch (error) {
        if (isApiAbortError(error)) {
          return;
        }
        setActions(EMPTY_ACTIONS);
        setActionError(reviewErrorText(error, "审批记录暂时不可用。"));
      } finally {
        if (actionAbortRef.current === controller) {
          actionAbortRef.current = null;
          setActionLoading(false);
        }
      }
    },
    [],
  );

  const loadFilterEmployees = useCallback(
    async (
      organizationId: string,
      offset: number,
      nextFilters: ReviewAuditFilters,
    ) => {
      const previous = filterEmployeeAbortRef.current;
      if (previous && !previous.signal.aborted) {
        previous.abort(new ApiRequestAbortedError("筛选员工请求已替换。"));
      }
      const controller = new AbortController();
      filterEmployeeAbortRef.current = controller;
      setFilterEmployeeLoading(true);
      setFilterEmployeeError("");
      try {
        const data = await listReviewAuditEmployees({
          filters: nextFilters,
          offset,
          organizationId,
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setFilterEmployees(data);
          setFilterEmployeeOffset(offset);
        }
      } catch (error) {
        if (isApiAbortError(error)) {
          return;
        }
        setFilterEmployees(EMPTY_EMPLOYEES);
        setFilterEmployeeError(reviewErrorText(error, "筛选员工暂时不可用。"));
      } finally {
        if (filterEmployeeAbortRef.current === controller) {
          filterEmployeeAbortRef.current = null;
          setFilterEmployeeLoading(false);
        }
      }
    },
    [],
  );

  const loadFilteredActions = useCallback(
    async (
      organizationId: string,
      userId: number,
      offset: number,
      nextFilters: ReviewAuditFilters,
    ) => {
      const previous = filteredActionAbortRef.current;
      if (previous && !previous.signal.aborted) {
        previous.abort(new ApiRequestAbortedError("筛选结果请求已替换。"));
      }
      const controller = new AbortController();
      filteredActionAbortRef.current = controller;
      setFilteredActionLoading(true);
      setFilterError("");
      try {
        const data = await listReviewAuditActions({
          filters: nextFilters,
          offset,
          organizationId,
          signal: controller.signal,
          userId,
        });
        if (!controller.signal.aborted) {
          setFilteredActions(data);
          setFilteredActionOffset(offset);
        }
      } catch (error) {
        if (isApiAbortError(error)) {
          return;
        }
        setFilteredActions(EMPTY_ACTIONS);
        setFilterError(reviewErrorText(error, "筛选结果暂时不可用。"));
      } finally {
        if (filteredActionAbortRef.current === controller) {
          filteredActionAbortRef.current = null;
          setFilteredActionLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    if (status !== "authenticated" || !canUse) {
      setOrganizationLoading(false);
      setCatalogLoading(false);
      return;
    }
    void loadOrganizations(organizationOffset);
    if (isOwner) {
      void loadOrganizationCatalog();
    }
  }, [
    canUse,
    isOwner,
    loadOrganizationCatalog,
    loadOrganizations,
    organizationOffset,
    status,
  ]);

  useEffect(() => {
    if (status === "authenticated" && canUse) {
      void loadModules();
    }
  }, [canUse, loadModules, status]);

  useEffect(() => {
    if (status === "authenticated" && canUse && employeeOrganizationId && !filterMode) {
      void loadEmployees(employeeOrganizationId);
    }
  }, [canUse, employeeOrganizationId, filterMode, loadEmployees, status]);

  useEffect(() => {
    if (
      status === "authenticated" &&
      canUse &&
      !filterMode &&
      selectedOrganizationId &&
      selectedUserId !== null
    ) {
      void loadActions(selectedOrganizationId, selectedUserId, actionOffset);
    }
  }, [
    actionOffset,
    canUse,
    filterMode,
    loadActions,
    selectedOrganizationId,
    selectedUserId,
    status,
  ]);

  useEffect(() => {
    if (status === "authenticated" && canUse && filterMode) {
      const organizationId = filters.organizationId || (!isOwner ? employeeOrganizationId : "");
      if (!organizationId) {
        setFilterError("请选择组织后再筛选。");
        return;
      }
      if (selectedFilterUserId !== null) {
        void loadFilteredActions(
          organizationId,
          selectedFilterUserId,
          filteredActionOffset,
          filters,
        );
        return;
      }
      void loadFilterEmployees(organizationId, filterEmployeeOffset, filters);
    }
  }, [
    canUse,
    employeeOrganizationId,
    filterEmployeeOffset,
    filteredActionOffset,
    filterMode,
    filters,
    isOwner,
    loadFilterEmployees,
    loadFilteredActions,
    selectedFilterUserId,
    status,
  ]);

  function updateDraft(event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) {
    const { name, value } = event.target;
    setDraftFilters((current) => ({
      ...current,
      employeeId: name === "employee" ? undefined : current.employeeId,
      [name]: value || undefined,
    }));
  }

  function updateDraftOrganization(event: ChangeEvent<HTMLSelectElement>) {
    const organizationId = event.target.value || undefined;
    setDraftFilters((current) => ({
      ...current,
      employeeId: undefined,
      organizationId,
    }));
    setSelectedOrganizationId(organizationId ?? "");
    setSelectedUserId(null);
    setActions(EMPTY_ACTIONS);
  }

  function updateDraftEmployee(event: ChangeEvent<HTMLSelectElement>) {
    const employeeId = Number(event.target.value);
    setDraftFilters((current) => ({
      ...current,
      employeeId: Number.isFinite(employeeId) && employeeId > 0 ? employeeId : undefined,
    }));
  }

  function applyFilters() {
    if (isOwner && !draftFilters.organizationId) {
      setFilterError("请选择组织后再筛选。");
      return;
    }
    setFilterMode(true);
    setFilterError("");
    setFilterEmployeeOffset(0);
    setSelectedFilterUserId(draftFilters.employeeId ?? null);
    setFilteredActionOffset(0);
    setFilters(draftFilters);
    setFilterEmployees(EMPTY_EMPLOYEES);
    setFilteredActions(EMPTY_ACTIONS);
  }

  function clearFilters() {
    setFilterMode(false);
    setDraftFilters({});
    setFilters({});
    setFilterEmployees(EMPTY_EMPLOYEES);
    setFilterEmployeeOffset(0);
    setSelectedFilterUserId(null);
    setFilteredActions(EMPTY_ACTIONS);
    setFilteredActionOffset(0);
    setFilterError("");
    setSelectedOrganizationId(
      !isOwner && organizations.items[0] ? organizations.items[0].organization_id : "",
    );
    setSelectedUserId(null);
    setEmployees(EMPTY_EMPLOYEES);
    setActions(EMPTY_ACTIONS);
  }

  function selectOrganization(organization: ReviewAuditOrganization) {
    setSelectedOrganizationId(organization.organization_id);
    setSelectedUserId(null);
    setActions(EMPTY_ACTIONS);
    setActionOffset(0);
    setDetailEmployeeSearch("");
    if (isOwner) {
      setDraftFilters((current) => ({
        ...current,
        employeeId: undefined,
        organizationId: organization.organization_id,
      }));
    }
  }

  function selectDetailEmployee(event: ChangeEvent<HTMLSelectElement>) {
    const employeeId = Number(event.target.value);
    setSelectedUserId(Number.isFinite(employeeId) && employeeId > 0 ? employeeId : null);
    setActionOffset(0);
    setActions(EMPTY_ACTIONS);
  }

  if (status !== "authenticated") {
    return null;
  }

  if (!canUse) {
    return (
      <section className="permission-denied">
        <span className="permission-denied-icon">
          <XCircle aria-hidden="true" size={22} />
        </span>
        <div>
          <h2>无法查看审批审计</h2>
          <p>该区域仅对owner和组织管理员开放。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="review-audit" aria-label="审批行为审计">
      <div className="review-audit-heading">
        <div>
          <span className="eyebrow">审批审计</span>
          <h2>审批行为审计</h2>
          <p>
            {isOwner
              ? "按真实组织、员工和模块查看审批动作。"
              : "查看本组织员工的审批动作。"}
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={organizationLoading}
          onClick={() => {
            void loadOrganizations(organizationOffset);
            if (isOwner) {
              void loadOrganizationCatalog();
            }
          }}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={16} />
          {organizationLoading ? "同步中" : "刷新"}
        </button>
      </div>

      <form
        className="review-filter-bar"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters();
        }}
      >
        {isOwner ? (
          <label className="field-group">
            <span>组织</span>
            <select
              className="select-shell"
              disabled={catalogLoading}
              name="organizationId"
              onChange={updateDraftOrganization}
              value={draftFilters.organizationId ?? ""}
            >
              <option value="">选择组织</option>
              {organizationCatalog.items.map((organization) => (
                <option
                  key={organization.organization_id}
                  value={organization.organization_id}
                >
                  {organization.organization_name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="field-group">
          <span>员工搜索</span>
          <span className="input-shell">
            <input
              name="employee"
              onChange={updateDraft}
              value={draftFilters.employee ?? ""}
            />
          </span>
        </label>
        <label className="field-group">
          <span>员工</span>
          <select
            className="select-shell"
            disabled={!employeeOrganizationId || employeeLoading}
            name="employeeId"
            onChange={updateDraftEmployee}
            value={draftFilters.employeeId ?? ""}
          >
            <option value="">全部员工</option>
            {filteredEmployees.map((employee) => (
              <option key={employee.user_id} value={employee.user_id}>
                {employee.employee_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-group">
          <span>模块</span>
          <select
            className="select-shell"
            disabled={moduleLoading}
            name="module"
            onChange={updateDraft}
            value={draftFilters.module ?? ""}
          >
            <option value="">全部模块</option>
            {moduleOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-group">
          <span>开始时间</span>
          <span className="input-shell">
            <input
              name="startDate"
              onChange={updateDraft}
              type="date"
              value={draftFilters.startDate ?? ""}
            />
          </span>
        </label>
        <label className="field-group">
          <span>结束时间</span>
          <span className="input-shell">
            <input
              name="endDate"
              onChange={updateDraft}
              type="date"
              value={draftFilters.endDate ?? ""}
            />
          </span>
        </label>
        <div className="review-filter-actions">
          <button className="primary-button" type="submit">
            <Search aria-hidden="true" size={17} />
            筛选
          </button>
          <button className="secondary-button" onClick={clearFilters} type="button">
            清除
          </button>
        </div>
      </form>

      {filterError ? (
        <p className="review-warning" role="alert">
          {filterError}
        </p>
      ) : null}
      {moduleError ? (
        <p className="review-warning" role="alert">
          {moduleError}
        </p>
      ) : null}

      {filterMode ? (
        <section className="review-column review-results" aria-label="筛选结果">
          <div className="review-column-heading">
            <h3>{selectedFilterUserId === null ? "筛选员工" : "筛选结果"}</h3>
            {selectedFilterUserId === null ? (
              <PagingControls
                disabled={filterEmployeeLoading}
                hasNext={filterEmployees.items.length === REVIEW_AUDIT_PAGE_LIMIT}
                offset={filterEmployeeOffset}
                onPage={setFilterEmployeeOffset}
              />
            ) : (
              <PagingControls
                disabled={filteredActionLoading}
                hasNext={filteredActions.items.length === REVIEW_AUDIT_PAGE_LIMIT}
                offset={filteredActionOffset}
                onPage={setFilteredActionOffset}
              />
            )}
          </div>
          {filterEmployeeError ? (
            <p className="review-warning" role="alert">
              {filterEmployeeError}
            </p>
          ) : null}
          {selectedFilterUserId === null ? (
            filterEmployeeLoading && filterEmployees.items.length === 0 ? (
              <ReviewLoadingState label="正在加载员工" />
            ) : filterEmployees.items.length === 0 ? (
              <div className="review-empty">
                <strong>没有匹配的员工审批记录</strong>
              </div>
            ) : (
              <ol className="review-card-list">
                {filterEmployees.items.map((employee) => (
                  <li key={employee.user_id}>
                    <button
                      className="review-user-card"
                      onClick={() => {
                        setSelectedFilterUserId(employee.user_id);
                        setFilteredActionOffset(0);
                        setFilteredActions(EMPTY_ACTIONS);
                      }}
                      type="button"
                    >
                      <span className="review-card-icon">
                        <UserRound aria-hidden="true" size={18} />
                      </span>
                      <span className="review-card-main">
                        <strong>{employee.employee_name}</strong>
                        <small>
                          {employee.job_title || roleLabel(employee.employee_role)} · {employee.action_count} 条审批记录
                        </small>
                      </span>
                      <time>{formatDate(employee.latest_action_at)}</time>
                    </button>
                  </li>
                ))}
              </ol>
            )
          ) : filteredActionLoading && filteredActions.items.length === 0 ? (
            <ReviewLoadingState label="正在加载筛选结果" />
          ) : filteredActions.items.length === 0 ? (
            <div className="review-empty">
              <strong>没有匹配的审批记录</strong>
            </div>
          ) : (
            <ActionTimeline actions={filteredActions.items} />
          )}
          {selectedFilterUserId !== null && !draftFilters.employeeId ? (
            <div className="review-filter-actions">
              <button
                className="secondary-button"
                onClick={() => {
                  setSelectedFilterUserId(null);
                  setFilteredActions(EMPTY_ACTIONS);
                  setFilteredActionOffset(0);
                }}
                type="button"
              >
                返回员工
              </button>
            </div>
          ) : null}
        </section>
      ) : (
        <div className="review-audit-grid">
          <section className="review-column" aria-label="组织">
            <div className="review-column-heading">
              <h3>组织</h3>
              <PagingControls
                disabled={organizationLoading}
                hasNext={organizations.items.length === REVIEW_AUDIT_PAGE_LIMIT}
                offset={organizationOffset}
                onPage={(nextOffset) => {
                  setSelectedOrganizationId("");
                  setSelectedUserId(null);
                  setActions(EMPTY_ACTIONS);
                  setOrganizationOffset(nextOffset);
                }}
              />
            </div>
            {organizationError ? (
              <p className="review-warning" role="alert">
                {organizationError}
              </p>
            ) : null}
            {organizationLoading && organizations.items.length === 0 ? (
              <ReviewLoadingState label="正在加载组织" />
            ) : organizations.items.length === 0 ? (
              <div className="review-empty">
                <strong>暂无组织</strong>
              </div>
            ) : (
              <ol className="review-card-list">
                {organizations.items.map((organization) => (
                  <li key={organization.organization_id}>
                    <button
                      className={`review-org-card ${
                        selectedOrganizationId === organization.organization_id
                          ? "selected"
                          : ""
                      }`}
                      onClick={() => selectOrganization(organization)}
                      type="button"
                    >
                      <span className="review-card-icon">
                        <Building2 aria-hidden="true" size={18} />
                      </span>
                      <span className="review-card-main">
                        <strong>{organization.organization_name}</strong>
                        <small>
                          {organization.action_count > 0
                            ? `${organization.employee_count} 名员工 · ${organization.action_count} 条审批记录`
                            : "暂无审批任务"}
                        </small>
                      </span>
                      <time>{formatDate(organization.latest_action_at)}</time>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {selectedOrganization ? (
            <section className="review-column" aria-label="员工">
              <div className="review-column-heading">
                <h3>{selectedOrganization.organization_name}</h3>
              </div>
              {employeeError ? (
                <p className="review-warning" role="alert">
                  {employeeError}
                </p>
              ) : null}
              <label className="field-group">
                <span>员工搜索</span>
                <span className="input-shell">
                  <input
                    onChange={(event) => setDetailEmployeeSearch(event.target.value)}
                    value={detailEmployeeSearch}
                  />
                </span>
              </label>
              <label className="field-group">
                <span>员工</span>
                <select
                  className="select-shell"
                  disabled={employeeLoading || employees.items.length === 0}
                  onChange={selectDetailEmployee}
                  value={selectedUserId ?? ""}
                >
                  <option value="">选择员工</option>
                  {filteredEmployees.map((employee) => (
                    <option key={employee.user_id} value={employee.user_id}>
                      {employee.employee_name}
                    </option>
                  ))}
                </select>
              </label>
              {employeeLoading ? (
                <ReviewLoadingState label="正在加载员工" />
              ) : employees.items.length === 0 ? (
                <div className="review-empty">
                  <strong>该组织暂无员工</strong>
                </div>
              ) : (
                <ol className="review-card-list">
                  {filteredEmployees.map((employee) => (
                    <li key={employee.user_id}>
                      <button
                        className={`review-user-card ${
                          selectedUserId === employee.user_id ? "selected" : ""
                        }`}
                        onClick={() => {
                          setSelectedUserId(employee.user_id);
                          setActionOffset(0);
                          setActions(EMPTY_ACTIONS);
                        }}
                        type="button"
                      >
                        <span className="review-card-icon">
                          <UserRound aria-hidden="true" size={18} />
                        </span>
                        <span className="review-card-main">
                          <strong>{employee.employee_name}</strong>
                          <small>
                            {employee.job_title || roleLabel(employee.employee_role)}
                          </small>
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          ) : null}

          {selectedOrganization ? (
            <section className="review-column review-action-column" aria-label="审批记录">
              <div className="review-column-heading">
                <h3>审批记录</h3>
                <PagingControls
                  disabled={actionLoading || selectedUserId === null}
                  hasNext={actions.items.length === REVIEW_AUDIT_PAGE_LIMIT}
                  offset={actionOffset}
                  onPage={setActionOffset}
                />
              </div>
              {actionError ? (
                <p className="review-warning" role="alert">
                  {actionError}
                </p>
              ) : null}
              {!selectedEmployee ? (
                <div className="review-empty">
                  <strong>选择员工后显示记录</strong>
                </div>
              ) : actionLoading && actions.items.length === 0 ? (
                <ReviewLoadingState label="正在加载审批记录" />
              ) : actions.items.length === 0 ? (
                <div className="review-empty">
                  <strong>暂无审批任务</strong>
                </div>
              ) : (
                <ActionTimeline actions={actions.items} />
              )}
            </section>
          ) : null}
        </div>
      )}
    </section>
  );
}
