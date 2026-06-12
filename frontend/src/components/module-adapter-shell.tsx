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
  action_panel: "Action panel",
  audit_log_view: "Audit log view",
  dashboard_card: "Dashboard card",
  detail_page: "Detail page",
  future_approval_panel: "Future approval panel",
  module_page: "Module page",
  navigation: "Navigation",
  settings_panel: "Settings panel",
  status_widget: "Status widget",
};

const BINDING_LABELS: Record<AdapterBindingSummary["binding_type"], string> = {
  api: "API",
  navigation: "Navigation",
  page: "Page",
  route: "Route",
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
  description = "This adapter is pending, disabled, or unavailable. No live business action is connected.",
  title = "Adapter Surface",
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
    return <span className="adapter-muted">No binding declared.</span>;
  }

  return (
    <ul className="adapter-binding-list">
      {bindings.map((binding) => (
        <li key={`${binding.binding_type}:${binding.key}`}>
          <span>{BINDING_LABELS[binding.binding_type]}</span>
          <strong>{binding.key}</strong>
          <small>
            {binding.method ? `${binding.method} ` : ""}
            {binding.route ?? binding.api_namespace ?? "no_api"}
          </small>
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
        <h3>Supported surfaces</h3>
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
        <h3>Capabilities</h3>
      </div>
      {adapter.capabilities.length === 0 ? (
        <span className="adapter-muted">No capability declared.</span>
      ) : (
        <ul className="adapter-compact-list">
          {adapter.capabilities.map((capability) => (
            <li key={capability.capability_key}>
              <strong>{capability.display_name}</strong>
              <span>{capability.capability_key}</span>
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
        <strong>{contract.action_key}</strong>
        <span>{`${contract.input_contract} -> ${contract.output_contract}`}</span>
        <small>{state.execution_message}</small>
        {state.approval_message ? <small>{state.approval_message}</small> : null}
        <small>{state.no_execute_reason}</small>
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
        <h3>Action contracts</h3>
      </div>
      {adapter.action_contracts.length === 0 ? (
        <span className="adapter-muted">No action contract declared.</span>
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
        <h3>Data contracts</h3>
      </div>
      {contracts.length === 0 ? (
        <span className="adapter-muted">No data contract declared.</span>
      ) : (
        <ul className="adapter-compact-list">
          {contracts.map((contract) => (
            <li key={`${contract.type}:${contract.key}`}>
              <strong>{contract.key}</strong>
              <span>{contract.type}</span>
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
        <h3>Dependencies</h3>
      </div>
      {dependencies.length === 0 ? (
        <span className="adapter-muted">No external dependency declared.</span>
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
  } = useAdapterStateForModule(targetModuleKey);

  if (!targetModuleKey || accessState?.hidden === true) {
    return null;
  }

  if (adapterMetadataUnavailable || !adapter) {
    return (
      <section className="adapter-shell" aria-label="Adapter Surface">
        <AdapterUnavailableNotice description="Adapter metadata unavailable. Adapter access unknown." />
      </section>
    );
  }

  const surfaceState = getAdapterSurfaceState(adapter, accessState, surface);
  const unavailable =
    adapterAccessUnknown ||
    !accessState ||
    isAdapterLocked(accessState) ||
    isAdapterUnavailable(accessState);

  return (
    <section className="adapter-shell" aria-label="Adapter Surface">
      <div className="adapter-shell-heading">
        <div>
          <span className="eyebrow">Adapter Surface</span>
          <h2>{adapter.display_name}</h2>
          <p>
            Adapter contract is available, but execution is not connected yet.
          </p>
        </div>
        <AdapterStatusBadge status={adapter.adapter_status} />
      </div>

      {unavailable || surfaceState.disabled ? (
        <AdapterUnavailableNotice
          description={
            accessState?.reason ||
            surfaceState.reason ||
            "This adapter is pending, disabled, or unavailable. No live business action is connected."
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
