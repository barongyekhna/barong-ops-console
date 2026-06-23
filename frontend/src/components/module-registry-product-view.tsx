"use client";

import {
  Boxes,
  KeyRound,
  Plus,
  RotateCcw,
  Save,
  Trash2,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import { ApiError } from "@/lib/api";
import {
  createApiKey,
  createApiKeyBinding,
  deleteApiKey,
  deleteApiKeyBinding,
  listApiKeyBindings,
  listApiKeys,
  updateApiKey,
  type ApiKeyBindingRecord,
  type ApiKeyRecord,
} from "@/lib/api-key-orchestration-api";
import {
  listModuleControlCenter,
  updateModuleControlState,
  type ModuleControlCenterResponse,
  type ModuleControlState,
} from "@/lib/module-control-api";
import {
  moduleControlToggleKey,
  optimisticModuleControlState,
  replaceModuleControlCenterItem,
} from "@/lib/module-control-state";
import {
  listOrganizations,
  type OrganizationOption,
} from "@/lib/users-api";

const MODULE_PAGE_LIMIT = 10;
const MODULE_DESCRIPTIONS: Record<string, string> = {
  "admin.agents": "查看已接入的自动化助手。",
  "admin.modules": "查看当前工作台已开放的功能区。",
  "admin.organizations": "管理组织和组织管理员。",
  "admin.permissions": "管理账号访问范围。",
  "admin.settings": "查看系统设置状态。",
  "admin.users": "管理工作台账号和角色。",
  "business.approvals": "处理待审批事项。",
  "business.reviews": "查看审批行为和审核记录。",
  "core.dashboard": "查看工作台首页。",
  "system.errors": "查看系统异常记录。",
  "system.memory_events": "查看运行记录。",
  "system.operation_logs": "查看操作记录。",
};

function humanState(value: string) {
  const labels: Record<string, string> = {
    adapter_pending: "配置中",
    allowed: "可用",
    backend_unavailable: "暂不可用",
    forbidden: "无权访问",
    hidden: "已隐藏",
    mock: "预览",
    no_execution: "待配置",
    partial: "部分可用",
  };
  return labels[value] ?? "暂不可用";
}

function humanVisibility(value: string) {
  const labels: Record<string, string> = {
    active: "正常",
    backend_unavailable: "暂不可用",
    hidden: "不可见",
    unknown: "确认中",
    unavailable: "暂不可见",
    visible: "可见",
  };
  return labels[value] ?? "确认中";
}

function humanExecutionMode(value: string) {
  const labels: Record<string, string> = {
    live: "已启用",
    mock: "预览",
    off: "未启用",
    shadow: "试运行",
  };
  return labels[value] ?? "确认中";
}

function moduleDescription(moduleKey: string) {
  return MODULE_DESCRIPTIONS[moduleKey] ?? "查看该功能区当前状态。";
}

function moduleReadinessText(value: string) {
  if (value === "allowed") {
    return "可正常使用";
  }
  if (value === "forbidden") {
    return "需要开通权限";
  }
  if (value === "hidden") {
    return "暂未开放";
  }
  if (value === "adapter_pending") {
    return "配置中";
  }
  return "暂不可用";
}

function messageFromError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "请重新登录后再操作。";
    }
    if (error.status === 403) {
      return "当前账号无权执行此操作。";
    }
    if (error.status >= 500) {
      return "后端响应暂未返回可用数据。";
    }
    return error.message || fallback;
  }
  return fallback;
}

function ReadOnlyModuleRegistryView() {
  const {
    executionState,
    isLoading: isCapabilityLoading,
    items,
    orgContext,
  } = useFrontendCapabilityState();
  const moduleAccess = useModuleAccess();
  const [offset, setOffset] = useState(0);
  const isLoading = isCapabilityLoading || moduleAccess.isLoading;
  const refresh = moduleAccess.refresh;
  const registryError = moduleAccess.registryError;
  const registryUnavailable = moduleAccess.registryUnavailable;
  const productItems = useMemo(
    () =>
      items.filter(
        (item) => item.route_bound && item.sidebar_state !== "hidden",
      ),
    [items],
  );
  const visibleCount = productItems.filter((item) => item.org_visibility === "visible").length;
  const hiddenCount = productItems.filter((item) => item.state === "hidden").length;
  const partialCount = productItems.filter(
    (item) =>
      item.state === "partial" ||
      item.state === "adapter_pending" ||
      item.state === "mock" ||
      item.state === "no_execution" ||
      item.state === "backend_unavailable",
  ).length;
  const allowedCount = productItems.filter((item) => item.state === "allowed").length;
  const pagedItems = productItems.slice(offset, offset + MODULE_PAGE_LIMIT);

  if (!isLoading && registryUnavailable && productItems.length === 0) {
    return (
      <CapabilityEmptyStateEngine
        action={
          <button className="primary-button" onClick={() => void refresh()}>
            <RotateCcw aria-hidden="true" size={17} />
            重试
          </button>
        }
        icon={Boxes}
        reason={registryError?.message ?? "功能区暂时不可用。"}
        required_execution_mode="查看功能区。"
        required_module_state="功能区可用。"
        required_org_state="组织状态正常。"
        required_permission="查看功能区。"
        state="missing_feature"
        title="功能区暂时不可用"
        unlock_condition="稍后重试。"
      />
    );
  }

  return (
    <section className="module-registry-workspace" aria-label="功能区">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">功能区</span>
          <h2>工作台功能区</h2>
          <p>
            查看当前工作台可用功能、可见范围和操作准备情况。
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void refresh()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          {isLoading ? "同步中" : "刷新"}
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>功能区</span>
          <strong>{productItems.length}</strong>
        </div>
        <div>
          <span>可用</span>
          <strong>{allowedCount}</strong>
        </div>
        <div>
          <span>配置中</span>
          <strong>{partialCount}</strong>
        </div>
        <div>
          <span>已隐藏</span>
          <strong>{hiddenCount}</strong>
        </div>
        <div>
          <span>组织可见</span>
          <strong>{visibleCount}</strong>
        </div>
        <div>
          <span>已登记</span>
          <strong>{moduleAccess.moduleAccessUnknown ? "确认中" : "已同步"}</strong>
        </div>
        <div>
          <span>组织状态</span>
          <strong>{humanVisibility(orgContext.state)}</strong>
        </div>
        <div>
          <span>操作状态</span>
          <strong>{humanExecutionMode(executionState.execution_mode)}</strong>
        </div>
      </div>

      {registryUnavailable ? (
        <p className="ops-warning">
          {registryError?.message ??
            "功能区详情暂时不可用，已保留可用导航。"}
        </p>
      ) : null}

      {pagedItems.length === 0 && !isLoading ? (
        <div className="ops-empty-state" role="status">
          <strong>暂无数据</strong>
          <span>当前没有可显示的功能区。</span>
        </div>
      ) : (
        <div className="module-registry-table-scroll">
          <table className="module-registry-table">
            <thead>
              <tr>
                <th>功能区</th>
                <th>状态</th>
                <th>可见范围</th>
                <th>准备情况</th>
                <th>操作状态</th>
              </tr>
            </thead>
            <tbody>
              {pagedItems.map((item) => (
                <tr key={item.module_key}>
                  <td>
                    <strong>{item.label}</strong>
                    <small>{moduleDescription(item.module_key)}</small>
                  </td>
                  <td>
                    <span className={`capability-state-pill ${item.state}`}>
                      {humanState(item.state)}
                    </span>
                    <small>{moduleReadinessText(item.state)}</small>
                  </td>
                  <td>
                    <strong>{humanVisibility(item.org_visibility)}</strong>
                    <span>按当前账号和组织范围显示</span>
                  </td>
                  <td>
                    <strong>{moduleReadinessText(item.state)}</strong>
                    <span>不显示内部配置字段</span>
                  </td>
                  <td>
                    <strong>{humanExecutionMode(item.execution_mode)}</strong>
                    <span>按系统状态自动判断</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="review-pager">
        <button
          className="secondary-button"
          disabled={isLoading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - MODULE_PAGE_LIMIT))}
          type="button"
        >
          上一页
        </button>
        <span>{Math.floor(offset / MODULE_PAGE_LIMIT) + 1}</span>
        <button
          className="secondary-button"
          disabled={isLoading || offset + MODULE_PAGE_LIMIT >= productItems.length}
          onClick={() => setOffset(offset + MODULE_PAGE_LIMIT)}
          type="button"
        >
          下一页
        </button>
      </div>
    </section>
  );
}

function runtimeStatusLabel(status: string) {
  if (status === "active") {
    return "运行中";
  }
  if (status === "error") {
    return "异常";
  }
  return "已停用";
}

function keyStatusLabel(status: string) {
  if (status === "active") {
    return "可用";
  }
  if (status === "disabled") {
    return "已停用";
  }
  return "已删除";
}

function organizationLabel(organization: OrganizationOption) {
  return organization.org_name.trim() || "未命名组织";
}

function validOrganizationId(
  organizations: OrganizationOption[],
  currentOrgId: string,
) {
  if (
    currentOrgId &&
    organizations.some((organization) => organization.org_id === currentOrgId)
  ) {
    return currentOrgId;
  }
  return organizations[0]?.org_id ?? "";
}

function OwnerModuleControlCenter() {
  const [controlCenter, setControlCenter] =
    useState<ModuleControlCenterResponse | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationOption[]>([]);
  const [organizationCount, setOrganizationCount] = useState(0);
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [bindings, setBindings] = useState<ApiKeyBindingRecord[]>([]);
  const [isOrganizationsLoading, setIsOrganizationsLoading] = useState(true);
  const [isControlDataLoading, setIsControlDataLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [pendingModuleToggleIds, setPendingModuleToggleIds] = useState<
    Set<string>
  >(new Set());
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [keyForm, setKeyForm] = useState({
    key_value: "",
    name: "",
    org_id: "",
    url: "",
  });
  const [bindingForm, setBindingForm] = useState({
    key_alias: "default",
    key_id: "",
    module_id: "",
    org_id: "",
  });
  const [editingKeyId, setEditingKeyId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    key_value: "",
    name: "",
    url: "",
  });

  const refresh = useCallback(async () => {
    setError("");
    setIsOrganizationsLoading(true);
    setIsControlDataLoading(true);

    let hydratedOrganizations: OrganizationOption[] = [];
    try {
      const organizationsResponse = await listOrganizations(100, 0);
      hydratedOrganizations = organizationsResponse.items;
      setOrganizations(hydratedOrganizations);
      setOrganizationCount(organizationsResponse.count);

      setKeyForm((current) => ({
        ...current,
        org_id: validOrganizationId(hydratedOrganizations, current.org_id),
      }));
      setBindingForm((current) => ({
        ...current,
        org_id: validOrganizationId(hydratedOrganizations, current.org_id),
      }));
    } catch (organizationLoadError) {
      setOrganizations([]);
      setOrganizationCount(0);
      setError(
        messageFromError(
          organizationLoadError,
          "组织数据暂时不可用，请稍后再试。",
        ),
      );
      setIsOrganizationsLoading(false);
      setIsControlDataLoading(false);
      return;
    } finally {
      setIsOrganizationsLoading(false);
    }

    try {
      const [center, keys, keyBindings] = await Promise.all([
        listModuleControlCenter(),
        listApiKeys(),
        listApiKeyBindings(),
      ]);
      setControlCenter(center);
      setApiKeys(keys.items);
      setBindings(keyBindings.items);

      const controlGroupsByOrgId = new Map(
        center.organizations.map((group) => [group.org_id, group]),
      );

      setKeyForm((current) => ({
        ...current,
        org_id: validOrganizationId(hydratedOrganizations, current.org_id),
      }));
      setBindingForm((current) => {
        const selectedOrg = validOrganizationId(
          hydratedOrganizations,
          current.org_id,
        );
        const orgModules = controlGroupsByOrgId.get(selectedOrg)?.modules ?? [];
        const orgKeys = keys.items.filter((key) => key.org_id === selectedOrg);

        return {
          key_alias: current.key_alias || "default",
          key_id:
            current.key_id && orgKeys.some((key) => key.key_id === current.key_id)
              ? current.key_id
              : orgKeys[0]?.key_id || "",
          module_id:
            current.module_id &&
            orgModules.some((module) => module.module_id === current.module_id)
              ? current.module_id
              : orgModules[0]?.module_id || "",
          org_id: selectedOrg,
        };
      });
    } catch (loadError) {
      setError(messageFromError(loadError, "后端响应暂未返回可用数据。"));
    } finally {
      setIsControlDataLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const controlGroupsByOrgId = useMemo(() => {
    const groups = new Map<string, ModuleControlCenterResponse["organizations"][number]>();
    for (const group of controlCenter?.organizations ?? []) {
      groups.set(group.org_id, group);
    }
    return groups;
  }, [controlCenter]);

  const selectedOrgModules = useMemo(() => {
    const orgId = bindingForm.org_id || keyForm.org_id;
    return controlGroupsByOrgId.get(orgId)?.modules ?? [];
  }, [bindingForm.org_id, controlGroupsByOrgId, keyForm.org_id]);

  const hasPendingModuleToggles = pendingModuleToggleIds.size > 0;

  const availableKeysForOrg = useMemo(
    () => apiKeys.filter((key) => key.org_id === bindingForm.org_id),
    [apiKeys, bindingForm.org_id],
  );

  const moduleGroups = useMemo(
    () =>
      organizations.map((organization) => {
        const centerGroup = controlGroupsByOrgId.get(organization.org_id);
        return {
          modules: centerGroup?.modules ?? [],
          org_id: organization.org_id,
          org_name: organizationLabel(organization),
        };
      }),
    [controlGroupsByOrgId, organizations],
  );

  const moduleNameById = useMemo(() => {
    const names = new Map<string, string>();
    for (const group of controlCenter?.organizations ?? []) {
      for (const module of group.modules) {
        names.set(module.module_id, module.display_name);
      }
    }
    return names;
  }, [controlCenter]);

  function handleKeyOrganizationChange(orgId: string) {
    setKeyForm((current) => ({
      ...current,
      org_id: orgId,
    }));
  }

  function handleBindingOrganizationChange(orgId: string) {
    const modules =
      controlGroupsByOrgId.get(orgId)?.modules ?? [];
    const keys = apiKeys.filter((key) => key.org_id === orgId);
    setBindingForm((current) => ({
      ...current,
      key_id: keys[0]?.key_id || "",
      module_id: modules[0]?.module_id || "",
      org_id: orgId,
    }));
  }

  async function toggleModule(module: ModuleControlState) {
    const nextEnabled = !module.enabled;
    const toggleKey = moduleControlToggleKey(module);

    setPendingModuleToggleIds((current) => {
      const next = new Set(current);
      next.add(toggleKey);
      return next;
    });
    setNotice("");
    setError("");
    setControlCenter((current) =>
      replaceModuleControlCenterItem(
        current,
        optimisticModuleControlState(module, nextEnabled),
      ),
    );

    try {
      const response = await updateModuleControlState({
        enabled: nextEnabled,
        moduleId: module.module_id,
        orgId: module.org_id,
      });
      setControlCenter((current) =>
        replaceModuleControlCenterItem(current, response.item),
      );
      setNotice("模块状态已更新。");
    } catch (toggleError) {
      setControlCenter((current) =>
        replaceModuleControlCenterItem(current, module),
      );
      setError(messageFromError(toggleError, "模块状态更新失败。"));
    } finally {
      setPendingModuleToggleIds((current) => {
        const next = new Set(current);
        next.delete(toggleKey);
        return next;
      });
    }
  }

  async function submitKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setNotice("");
    setError("");
    try {
      await createApiKey(keyForm);
      setKeyForm((current) => ({ ...current, key_value: "", name: "", url: "" }));
      await refresh();
      setNotice("密钥已新增。");
    } catch (createError) {
      setError(messageFromError(createError, "密钥新增失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  function startEditKey(key: ApiKeyRecord) {
    setEditingKeyId(key.key_id);
    setEditForm({ key_value: "", name: key.name, url: key.url });
  }

  async function saveKeyEdit(keyId: string) {
    setIsSaving(true);
    setNotice("");
    setError("");
    try {
      const payload = {
        name: editForm.name,
        url: editForm.url,
        ...(editForm.key_value ? { key_value: editForm.key_value } : {}),
      };
      await updateApiKey(keyId, payload);
      setEditingKeyId(null);
      setEditForm({ key_value: "", name: "", url: "" });
      await refresh();
      setNotice("密钥已更新。");
    } catch (updateError) {
      setError(messageFromError(updateError, "密钥更新失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  async function removeKey(keyId: string) {
    setIsSaving(true);
    setNotice("");
    setError("");
    try {
      await deleteApiKey(keyId);
      await refresh();
      setNotice("密钥已删除。");
    } catch (deleteError) {
      setError(messageFromError(deleteError, "密钥删除失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  async function submitBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setNotice("");
    setError("");
    try {
      await createApiKeyBinding(bindingForm);
      await refresh();
      setNotice("模块绑定已更新。");
    } catch (bindingError) {
      setError(messageFromError(bindingError, "模块绑定失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  async function removeBinding(bindingId: string) {
    setIsSaving(true);
    setNotice("");
    setError("");
    try {
      await deleteApiKeyBinding(bindingId);
      await refresh();
      setNotice("模块绑定已移除。");
    } catch (bindingError) {
      setError(messageFromError(bindingError, "模块绑定移除失败。"));
    } finally {
      setIsSaving(false);
    }
  }

  const isLoading = isOrganizationsLoading || isControlDataLoading;
  const hasOrganizations = organizations.length > 0;
  const organizationSelectDisabled =
    isSaving || !hasOrganizations || (isOrganizationsLoading && !hasOrganizations);
  const moduleCount =
    moduleGroups.reduce((sum, group) => sum + group.modules.length, 0) ||
    controlCenter?.module_count ||
    0;
  const activeModuleCount =
    moduleGroups.reduce(
      (sum, group) => sum + group.modules.filter((module) => module.enabled).length,
      0,
    );
  const errorModuleCount =
    moduleGroups.reduce(
      (sum, group) =>
        sum + group.modules.filter((module) => module.runtime_status === "error").length,
      0,
    );

  return (
    <section className="module-registry-workspace" aria-label="模块管理中心">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">owner</span>
          <h2>模块管理中心</h2>
          <p>按组织管理模块开关、运行状态和密钥绑定。</p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading || isSaving || hasPendingModuleToggles}
          onClick={() => void refresh()}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={17} />
          {isLoading ? "同步中" : "刷新"}
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>组织</span>
          <strong>{organizationCount}</strong>
        </div>
        <div>
          <span>模块</span>
          <strong>{moduleCount}</strong>
        </div>
        <div>
          <span>运行中</span>
          <strong>{activeModuleCount}</strong>
        </div>
        <div>
          <span>异常</span>
          <strong>{errorModuleCount}</strong>
        </div>
        <div>
          <span>密钥</span>
          <strong>{apiKeys.length}</strong>
        </div>
        <div>
          <span>绑定</span>
          <strong>{bindings.length}</strong>
        </div>
      </div>

      {error ? (
        <p className="ops-warning" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="ops-warning product-notice" role="status">
          {notice}
        </p>
      ) : null}

      <div className="module-control-org-list">
        {isOrganizationsLoading && organizations.length === 0 ? (
          <section className="ops-panel ops-panel-wide">
            <div className="ops-panel-heading">
              <div>
                <h3>组织数据加载中</h3>
                <p>正在同步后端组织列表。</p>
              </div>
              <span className="skeleton-chip" aria-hidden="true" />
            </div>
            <div className="skeleton-grid" aria-hidden="true">
              <span className="skeleton-card" />
              <span className="skeleton-card" />
              <span className="skeleton-card" />
            </div>
          </section>
        ) : null}
        {!isOrganizationsLoading && organizations.length === 0 ? (
          <section className="ops-panel ops-panel-wide">
            <div className="ops-panel-heading">
              <div>
                <h3>组织数据未返回</h3>
                <p>请刷新后重试。</p>
              </div>
              <button
                className="secondary-button"
                disabled={isLoading || isSaving || hasPendingModuleToggles}
                onClick={() => void refresh()}
                type="button"
              >
                <RotateCcw aria-hidden="true" size={17} />
                刷新
              </button>
            </div>
          </section>
        ) : null}
        {moduleGroups.map((group) => (
          <section className="ops-panel ops-panel-wide" key={group.org_id}>
            <div className="ops-panel-heading">
              <div>
                <h3>{group.org_name}</h3>
                <p>当前组织已同步真实模块清单。</p>
              </div>
              <span className="ops-source">{group.modules.length} 个模块</span>
            </div>
            {isControlDataLoading && group.modules.length === 0 ? (
              <div className="ops-empty-state" role="status">
                <strong>模块数据加载中</strong>
                <span>正在同步该组织的模块状态。</span>
                <div className="skeleton-grid" aria-hidden="true">
                  <span className="skeleton-card" />
                  <span className="skeleton-card" />
                </div>
              </div>
            ) : group.modules.length === 0 ? (
              <div className="ops-empty-state" role="status">
                <strong>模块数据暂未返回</strong>
                <span>请刷新后重试。</span>
              </div>
            ) : (
              <div className="module-control-card-grid">
                {group.modules.map((module) => {
                  const togglePending = pendingModuleToggleIds.has(
                    moduleControlToggleKey(module),
                  );

                  return (
                    <article className="module-control-card" key={module.module_id}>
                      <div className="module-control-card-top">
                        <div>
                          <strong>{module.display_name}</strong>
                          <span>{moduleDescription(module.module_id)}</span>
                        </div>
                        <span
                          className={`module-control-status ${module.runtime_status}`}
                        >
                          {runtimeStatusLabel(module.runtime_status)}
                        </span>
                      </div>
                      <div className="module-control-card-bottom">
                        <label className="module-toggle">
                          <input
                            checked={module.enabled}
                            disabled={isSaving || togglePending}
                            onChange={() => void toggleModule(module)}
                            type="checkbox"
                          />
                          <span aria-hidden="true" />
                        </label>
                        <span>{module.enabled ? "已启用" : "已停用"}</span>
                      </div>
                      {module.runtime_error_message ? (
                        <p className="module-error-badge">
                          运行异常：{module.runtime_error_message}
                        </p>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        ))}
      </div>

      <section className="ops-panel ops-panel-wide">
        <div className="ops-panel-heading">
          <div>
            <h3>密钥管理</h3>
            <p>密钥只写入后端，前端不会显示明文。</p>
          </div>
          <KeyRound aria-hidden="true" size={18} />
        </div>

        <form className="api-key-form" onSubmit={submitKey}>
          <label className="field-group">
            <span>组织</span>
            <span className="input-shell">
              <select
                disabled={organizationSelectDisabled}
                onChange={(event) => handleKeyOrganizationChange(event.target.value)}
                required
                value={keyForm.org_id}
              >
                {!hasOrganizations ? (
                  <option value="">
                    {isOrganizationsLoading ? "组织加载中" : "暂无组织"}
                  </option>
                ) : null}
                {organizations.map((organization) => (
                  <option key={organization.org_id} value={organization.org_id}>
                    {organizationLabel(organization)}
                  </option>
                ))}
              </select>
            </span>
          </label>
          <label className="field-group">
            <span>名称</span>
            <span className="input-shell">
              <input
                onChange={(event) =>
                  setKeyForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                required
                value={keyForm.name}
              />
            </span>
          </label>
          <label className="field-group">
            <span>服务地址</span>
            <span className="input-shell">
              <input
                onChange={(event) =>
                  setKeyForm((current) => ({
                    ...current,
                    url: event.target.value,
                  }))
                }
                placeholder="https://api.example.com"
                required
                type="url"
                value={keyForm.url}
              />
            </span>
          </label>
          <label className="field-group">
            <span>密钥</span>
            <span className="input-shell">
              <input
                autoComplete="off"
                onChange={(event) =>
                  setKeyForm((current) => ({
                    ...current,
                    key_value: event.target.value,
                  }))
                }
                required
                type="password"
                value={keyForm.key_value}
              />
            </span>
          </label>
          <button
            className="primary-button"
            disabled={isSaving || !keyForm.org_id || !hasOrganizations}
            type="submit"
          >
            <Plus aria-hidden="true" size={17} />
            新增密钥
          </button>
        </form>

        <div className="module-registry-table-scroll">
          <table className="module-registry-table api-key-table">
            <thead>
              <tr>
                <th>密钥</th>
                <th>服务地址</th>
                <th>名称</th>
                <th>已绑定模块</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((key) => {
                const isEditing = editingKeyId === key.key_id;
                return (
                  <tr key={key.key_id}>
                    <td>
                      <strong>已加密保存</strong>
                      <small>{keyStatusLabel(key.status)}</small>
                    </td>
                    <td>
                      {isEditing ? (
                        <span className="input-shell compact-input-shell">
                          <input
                            onChange={(event) =>
                              setEditForm((current) => ({
                                ...current,
                                url: event.target.value,
                              }))
                            }
                            type="url"
                            value={editForm.url}
                          />
                        </span>
                      ) : (
                        <span>{key.url}</span>
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <div className="api-key-edit-stack">
                          <span className="input-shell compact-input-shell">
                            <input
                              onChange={(event) =>
                                setEditForm((current) => ({
                                  ...current,
                                  name: event.target.value,
                                }))
                              }
                              value={editForm.name}
                            />
                          </span>
                          <span className="input-shell compact-input-shell">
                            <input
                              autoComplete="off"
                              onChange={(event) =>
                                setEditForm((current) => ({
                                  ...current,
                                  key_value: event.target.value,
                                }))
                              }
                              placeholder="留空表示不更换"
                              type="password"
                              value={editForm.key_value}
                            />
                          </span>
                        </div>
                      ) : (
                        <strong>{key.name}</strong>
                      )}
                    </td>
                    <td>
                      <span>
                        {key.assigned_module_ids
                          .map((moduleId) => moduleNameById.get(moduleId) ?? "已绑定模块")
                          .join("、") || "未绑定"}
                      </span>
                    </td>
                    <td>
                      <div className="module-control-action-row">
                        {isEditing ? (
                          <button
                            className="secondary-button icon-button"
                            disabled={isSaving}
                            onClick={() => void saveKeyEdit(key.key_id)}
                            title="保存"
                            type="button"
                          >
                            <Save aria-hidden="true" size={16} />
                          </button>
                        ) : (
                          <button
                            className="secondary-button"
                            disabled={isSaving}
                            onClick={() => startEditKey(key)}
                            type="button"
                          >
                            编辑
                          </button>
                        )}
                        <button
                          className="secondary-button icon-button"
                          disabled={isSaving}
                          onClick={() => void removeKey(key.key_id)}
                          title="删除"
                          type="button"
                        >
                          <Trash2 aria-hidden="true" size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <form className="api-key-binding-form" onSubmit={submitBinding}>
          <label className="field-group">
            <span>组织</span>
            <span className="input-shell">
              <select
                disabled={organizationSelectDisabled}
                onChange={(event) => handleBindingOrganizationChange(event.target.value)}
                required
                value={bindingForm.org_id}
              >
                {!hasOrganizations ? (
                  <option value="">
                    {isOrganizationsLoading ? "组织加载中" : "暂无组织"}
                  </option>
                ) : null}
                {organizations.map((organization) => (
                  <option key={organization.org_id} value={organization.org_id}>
                    {organizationLabel(organization)}
                  </option>
                ))}
              </select>
            </span>
          </label>
          <label className="field-group">
            <span>模块</span>
            <span className="input-shell">
              <select
                disabled={isSaving || selectedOrgModules.length === 0}
                onChange={(event) =>
                  setBindingForm((current) => ({
                    ...current,
                    module_id: event.target.value,
                  }))
                }
                required
                value={bindingForm.module_id}
              >
                {selectedOrgModules.map((module) => (
                  <option key={module.module_id} value={module.module_id}>
                    {module.display_name}
                  </option>
                ))}
              </select>
            </span>
          </label>
          <label className="field-group">
            <span>密钥</span>
            <span className="input-shell">
              <select
                disabled={isSaving || availableKeysForOrg.length === 0}
                onChange={(event) =>
                  setBindingForm((current) => ({
                    ...current,
                    key_id: event.target.value,
                  }))
                }
                required
                value={bindingForm.key_id}
              >
                {availableKeysForOrg.map((key) => (
                  <option key={key.key_id} value={key.key_id}>
                    {key.name}
                  </option>
                ))}
              </select>
            </span>
          </label>
          <label className="field-group">
            <span>用途名称</span>
            <span className="input-shell">
              <input
                onChange={(event) =>
                  setBindingForm((current) => ({
                    ...current,
                    key_alias: event.target.value,
                  }))
                }
                required
                value={bindingForm.key_alias}
              />
            </span>
          </label>
          <button
            className="primary-button"
            disabled={isSaving || !bindingForm.key_id || !bindingForm.module_id}
            type="submit"
          >
            <Save aria-hidden="true" size={17} />
            绑定
          </button>
        </form>

        {bindings.length > 0 ? (
          <div className="api-key-binding-list">
            {bindings.map((binding) => (
              <div className="api-key-binding-chip" key={binding.binding_id}>
                <span>{moduleNameById.get(binding.module_id) ?? "已绑定模块"}</span>
                <strong>{binding.key_name}</strong>
                <small>{binding.key_alias}</small>
                <button
                  className="secondary-button icon-button"
                  disabled={isSaving}
                  onClick={() => void removeBinding(binding.binding_id)}
                  title="移除"
                  type="button"
                >
                  <Trash2 aria-hidden="true" size={15} />
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}

export function ModuleRegistryProductView() {
  const { user } = useAuth();

  if (user?.role === "owner") {
    return <OwnerModuleControlCenter />;
  }

  return <ReadOnlyModuleRegistryView />;
}
