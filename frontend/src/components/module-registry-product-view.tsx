"use client";

import { Boxes, LoaderCircle, RotateCcw } from "lucide-react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import { useModuleAccess } from "@/components/module-access-provider";

function displayBinding(value: string) {
  return value && value !== "no_api" ? value : "No API";
}

export function ModuleRegistryProductView() {
  const {
    executionState,
    isLoading: isCapabilityLoading,
    items,
    orgContext,
  } = useFrontendCapabilityState();
  const moduleAccess = useModuleAccess();
  const isLoading = isCapabilityLoading || moduleAccess.isLoading;
  const refresh = moduleAccess.refresh;
  const registryError = moduleAccess.registryError;
  const registryUnavailable = moduleAccess.registryUnavailable;
  const visibleCount = items.filter((item) => item.org_visibility === "visible").length;
  const hiddenCount = items.filter((item) => item.state === "hidden").length;
  const partialCount = items.filter(
    (item) =>
      item.state === "partial" ||
      item.state === "adapter_pending" ||
      item.state === "mock" ||
      item.state === "no_execution" ||
      item.state === "backend_unavailable",
  ).length;
  const allowedCount = items.filter((item) => item.state === "allowed").length;

  if (!isLoading && registryUnavailable && items.length === 0) {
    return (
      <CapabilityEmptyStateEngine
        action={
          <button className="primary-button" onClick={() => void refresh()}>
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        }
        icon={Boxes}
        reason={registryError?.message ?? "Product areas are unavailable."}
        required_execution_mode="View access is available."
        required_module_state="Product areas must be available."
        required_org_state="Active workspace access is required."
        required_permission="modules.read"
        state="missing_feature"
        title="Product areas are unavailable"
        unlock_condition="Try again after product areas are available."
      />
    );
  }

  return (
    <section className="module-registry-workspace" aria-label="Product areas">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Product areas</span>
          <h2>Workspace product area map</h2>
          <p>
            Workspace visibility, access state, service mapping, and action
            readiness for product areas.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void refresh()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle className="spin" aria-hidden="true" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Total areas</span>
          <strong>{items.length}</strong>
        </div>
        <div>
          <span>Allowed</span>
          <strong>{allowedCount}</strong>
        </div>
        <div>
          <span>Partial</span>
          <strong>{partialCount}</strong>
        </div>
        <div>
          <span>Hidden</span>
          <strong>{hiddenCount}</strong>
        </div>
        <div>
          <span>Org visible</span>
          <strong>{visibleCount}</strong>
        </div>
        <div>
          <span>Module metadata</span>
          <strong>
            {moduleAccess.moduleAccessUnknown
              ? "Unknown"
              : moduleAccess.items.length}
          </strong>
        </div>
        <div>
          <span>Org state</span>
          <strong>{orgContext.state}</strong>
        </div>
        <div>
          <span>Action mode</span>
          <strong>{executionState.execution_mode}</strong>
        </div>
      </div>

      {registryUnavailable ? (
        <p className="ops-warning">
          {registryError?.message ??
            "Product area details are unavailable; navigation remains available."}
        </p>
      ) : null}

      <div className="module-registry-table-scroll">
        <table className="module-registry-table">
          <thead>
            <tr>
              <th>Area</th>
              <th>Product state</th>
              <th>Org visibility</th>
              <th>Permission</th>
              <th>Setup</th>
              <th>Actions</th>
              <th>API mapping</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.module_key}>
                <td>
                  <strong>{item.label}</strong>
                  <span>{item.module_key}</span>
                  <small>{item.description || item.route_namespace}</small>
                </td>
                <td>
                  <span className={`capability-state-pill ${item.state}`}>
                    {item.state}
                  </span>
                  <small>{item.module_status}</small>
                </td>
                <td>
                  <strong>{item.org_visibility}</strong>
                  <span>{item.required_org_state}</span>
                </td>
                <td>
                  <strong>{item.permission_state}</strong>
                  <span>{item.required_permission}</span>
                </td>
                <td>
                  <strong>{item.adapter_state}</strong>
                  <span>{item.required_module_state}</span>
                </td>
                <td>
                  <strong>{item.execution_mode}</strong>
                  <span>{item.blocked_reason}</span>
                </td>
                <td>
                  <strong>{displayBinding(item.api_binding.api_namespace)}</strong>
                  <span>
                    {item.route_bound
                      ? item.api_binding.route_namespace
                      : "No frontend route"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
