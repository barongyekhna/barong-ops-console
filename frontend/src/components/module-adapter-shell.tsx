"use client";

import {
  CircleSlash2,
  FileJson2,
  Layers3,
  ListChecks,
  PlugZap,
  ShieldAlert,
} from "lucide-react";
import { usePathname } from "next/navigation";

import { useAdapterStateForModule } from "@/components/adapter-access-provider";
import { ExecutionProviderStatusShell } from "@/components/execution-provider-status-shell";
import {
  findExecutionProviderAccessStateForAction,
  findExecutionProviderContractForAction,
  type ExecutionProviderAccessState,
  type ExecutionProviderContract,
} from "@/lib/execution-provider";
import {
  getActionContractState,
  getAdapterStatusLabel,
  getAdapterSurfaceState,
  getSafeDependencyNames,
  isAdapterLocked,
  isAdapterUnavailable,
  type AdapterActionContract,
  type AdapterBindingSummary,
  type AdapterSurface,
  type ModuleAdapterAccessState,
  type ModuleAdapterContract,
} from "@/lib/module-adapter";
import { findModuleRouteForPath } from "@/lib/module-registry";
import { navigationModuleRecords } from "@/lib/navigation";

const SURFACE_LABELS: Record<AdapterSurface, string> = {
  action_panel: "操作区",
  audit_log_view: "记录视图",
  dashboard_card: "首页概览",
  detail_page: "详情页",
  future_approval_panel: "审批区",
  module_page: "功能页",
  navigation: "导航",
  settings_panel: "设置区",
  status_widget: "状态组件",
};

const BINDING_LABELS: Record<AdapterBindingSummary["binding_type"], string> = {
  api: "服务",
  navigation: "导航",
  page: "页面",
  route: "路径",
};

export function AdapterStatusBadge({
  status,
}: {
  status: ModuleAdapterContract["adapter_status"] | "unknown";
}) {
  return (
    <span className={`adapter-status-badge ${status}`}>
      {getAdapterStatusLabel(status)}
    </span>
  );
}

export function AdapterUnavailableNotice({
  description = "该功能暂不可用，暂未连接可执行操作。",
  title = "功能状态",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="adapter-unavailable-notice" role="status">
      <CircleSlash2 aria-hidden="true" size={18} />
      <div>
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
    </div>
  );
}

function BindingList({
  bindings,
}: {
  bindings: AdapterBindingSummary[];
}) {
  if (bindings.length === 0) {
    return <span className="adapter-muted">暂无可显示连接。</span>;
  }

  return (
    <ul className="adapter-binding-list">
      {bindings.map((binding) => (
        <li key={`${binding.binding_type}:${binding.key}`}>
          <span>{BINDING_LABELS[binding.binding_type]}</span>
          <strong>已登记</strong>
          <small>不展示内部路径</small>
        </li>
      ))}
    </ul>
  );
}

export function AdapterSurfacePlaceholder({
  accessState,
  adapter,
}: {
  adapter: ModuleAdapterContract;
  accessState: ModuleAdapterAccessState | null;
}) {
  const bindings = [
    ...adapter.pages,
    ...adapter.nav_bindings,
    ...adapter.route_bindings,
    ...adapter.api_bindings,
  ];

  return (
    <div className="adapter-section">
      <div className="adapter-section-heading">
        <Layers3 aria-hidden="true" size={18} />
        <h3>可用位置</h3>
      </div>
      <div className="adapter-surface-grid">
        {adapter.supported_surfaces.map((surface) => {
          const state = getAdapterSurfaceState(adapter, accessState, surface);

          return (
            <div className="adapter-surface-row" key={surface}>
              <span>{SURFACE_LABELS[surface]}</span>
              <strong>{state.label}</strong>
            </div>
          );
        })}
      </div>
      <BindingList bindings={bindings} />
    </div>
  );
}

export function AdapterCapabilitiesList({
  adapter,
}: {
  adapter: ModuleAdapterContract;
}) {
  return (
    <div className="adapter-section">
      <div className="adapter-section-heading">
        <ListChecks aria-hidden="true" size={18} />
        <h3>能力说明</h3>
      </div>
      {adapter.capabilities.length === 0 ? (
        <span className="adapter-muted">暂无可显示能力。</span>
      ) : (
        <ul className="adapter-compact-list">
          {adapter.capabilities.map((capability) => (
            <li key={capability.capability_key}>
              <strong>{capability.display_name}</strong>
              <span>已登记</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ActionContractRow({
  accessState,
  adapter,
  contract,
  executionProviderAccessItems,
  executionProviders,
}: {
  contract: AdapterActionContract;
  adapter: ModuleAdapterContract;
  accessState: ModuleAdapterAccessState | null;
  executionProviderAccessItems: ExecutionProviderAccessState[];
  executionProviders: ExecutionProviderContract[];
}) {
  const providerAccessState = findExecutionProviderAccessStateForAction(
    {
      actionKey: contract.action_key,
      adapterKey: adapter.adapter_key,
      moduleKey: adapter.module_key,
    },
    executionProviderAccessItems,
  );
  const provider = findExecutionProviderContractForAction(
    {
      actionKey: contract.action_key,
      adapterKey: adapter.adapter_key,
      moduleKey: adapter.module_key,
    },
    executionProviders,
  );
  const state = getActionContractState(
    contract,
    accessState,
    providerAccessState,
  );

  return (
    <li>
      <div>
        <strong>操作能力</strong>
        <span>输入输出规则已登记</span>
        <small>{state.disabled ? "暂不可执行" : "可执行"}</small>
        {state.approval_message ? <small>需要审批</small> : null}
      </div>
      <ExecutionProviderStatusShell
        actionContract={contract}
        provider={provider}
        providerAccessState={providerAccessState}
      />
    </li>
  );
}

export function AdapterActionContractsList({
  accessState,
  adapter,
  executionProviderAccessItems,
  executionProviders,
}: {
  adapter: ModuleAdapterContract;
  accessState: ModuleAdapterAccessState | null;
  executionProviderAccessItems: ExecutionProviderAccessState[];
  executionProviders: ExecutionProviderContract[];
}) {
  return (
    <div className="adapter-section">
      <div className="adapter-section-heading">
        <PlugZap aria-hidden="true" size={18} />
        <h3>操作规则</h3>
      </div>
      {adapter.action_contracts.length === 0 ? (
        <span className="adapter-muted">暂无可显示操作规则。</span>
      ) : (
        <ul className="adapter-action-list">
          {adapter.action_contracts.map((contract) => (
            <ActionContractRow
              accessState={accessState}
              adapter={adapter}
              contract={contract}
              executionProviderAccessItems={executionProviderAccessItems}
              executionProviders={executionProviders}
              key={contract.action_key}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export function AdapterDataContractsSummary({
  adapter,
}: {
  adapter: ModuleAdapterContract;
}) {
  const contracts = [
    ...adapter.data_contracts.map((contract) => ({
      key: contract.contract_key,
      type: contract.object_type || "data",
    })),
    ...adapter.input_contracts.map((contract) => ({
      key: contract.contract_key,
      type: "input",
    })),
    ...adapter.output_contracts.map((contract) => ({
      key: contract.contract_key,
      type: "output",
    })),
  ];

  return (
    <div className="adapter-section">
      <div className="adapter-section-heading">
        <FileJson2 aria-hidden="true" size={18} />
        <h3>数据规则</h3>
      </div>
      {contracts.length === 0 ? (
        <span className="adapter-muted">暂无可显示数据规则。</span>
      ) : (
        <ul className="adapter-compact-list">
          {contracts.map((contract) => (
            <li key={`${contract.type}:${contract.key}`}>
              <strong>数据规则</strong>
              <span>已登记</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AdapterDependencySummary({
  adapter,
}: {
  adapter: ModuleAdapterContract;
}) {
  const dependencies = getSafeDependencyNames(adapter.dependency_declarations);

  return (
    <div className="adapter-section">
      <div className="adapter-section-heading">
        <ShieldAlert aria-hidden="true" size={18} />
        <h3>外部依赖</h3>
      </div>
      {dependencies.length === 0 ? (
        <span className="adapter-muted">暂无外部依赖。</span>
      ) : (
        <div className="adapter-dependency-list">
          {dependencies.map((dependency) => (
            <span key={dependency}>{dependency}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export function AdapterSurfaceShell({
  moduleKey,
  surface = "module_page",
}: {
  moduleKey?: string | null;
  surface?: AdapterSurface;
}) {
  const pathname = usePathname();
  const route = moduleKey
    ? null
    : findModuleRouteForPath(pathname, navigationModuleRecords);
  const targetModuleKey = moduleKey ?? route?.module_key ?? null;
  const {
    accessState,
    adapter,
    adapterAccessUnknown,
    adapterMetadataUnavailable,
    executionProviderAccessItems,
    executionProviders,
    isOwnerFullAccess,
  } = useAdapterStateForModule(targetModuleKey);

  if (!targetModuleKey || (accessState?.hidden === true && !isOwnerFullAccess)) {
    return null;
  }

  if (adapterMetadataUnavailable || !adapter) {
    return (
      <section className="adapter-shell" aria-label="功能状态">
        <AdapterUnavailableNotice description="功能状态暂不可用。" />
      </section>
    );
  }

  const surfaceState = getAdapterSurfaceState(adapter, accessState, surface);
  const unavailable =
    adapterAccessUnknown ||
    !accessState ||
    (!isOwnerFullAccess && isAdapterLocked(accessState)) ||
    isAdapterUnavailable(accessState);

  return (
    <section className="adapter-shell" aria-label="功能状态">
      <div className="adapter-shell-heading">
        <div>
          <span className="eyebrow">功能状态</span>
          <h2>{adapter.display_name}</h2>
          <p>
            该功能已登记，具体操作会按当前账号权限显示。
          </p>
        </div>
        <AdapterStatusBadge status={adapter.adapter_status} />
      </div>

      {unavailable || surfaceState.disabled ? (
        <AdapterUnavailableNotice
          description={
            accessState?.reason ||
            surfaceState.reason ||
            "该功能暂不可用，暂未连接可执行操作。"
          }
        />
      ) : null}

      <AdapterSurfacePlaceholder accessState={accessState} adapter={adapter} />
      <AdapterCapabilitiesList adapter={adapter} />
      <AdapterActionContractsList
        accessState={accessState}
        adapter={adapter}
        executionProviderAccessItems={executionProviderAccessItems}
        executionProviders={executionProviders}
      />
      <AdapterDataContractsSummary adapter={adapter} />
      <AdapterDependencySummary adapter={adapter} />
    </section>
  );
}
