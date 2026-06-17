"use client";

import { Boxes, LoaderCircle, RotateCcw } from "lucide-react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";

function displayBinding(value: string) {
  return value && value !== "no_api" ? value : "No API";
}

export function ModuleRegistryProductView() {
  const {
    executionState,
    isLoading,
    items,
    orgContext,
    permissionSnapshot,
    refresh,
    registryError,
    registryUnavailable,
  } = useFrontendCapabilityState();
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
        reason={registryError?.message ?? "Module registry is unavailable."}
        required_execution_mode="No execution mode required for registry read."
        required_module_state="C18 module registry API must be reachable."
        required_org_state="Active organization context must allow module registry read."
        required_permission="modules.read"
        state="backend_unavailable"
        title="Module registry unavailable"
        unlock_condition="Restore /modules/registry and /modules/me."
      />
    );
  }

  return (
    <section className="module-registry-workspace" aria-label="Module registry">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Capability Registry</span>
          <h2>Module capability map</h2>
          <p>
            Dynamic module list with C18 org visibility, C05 permission state,
            adapter state, API binding, and PRE20-Q execution mode.
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
          <span>Total modules</span>
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
          <span>Permission keys</span>
          <strong>
            {permissionSnapshot.is_owner_full_access
              ? "Owner"
              : permissionSnapshot.permission_count}
          </strong>
        </div>
        <div>
          <span>Org state</span>
          <strong>{orgContext.state}</strong>
        </div>
        <div>
          <span>Execution mode</span>
          <strong>{executionState.execution_mode}</strong>
        </div>
      </div>

      {registryUnavailable ? (
        <p className="ops-warning">
          {registryError?.message ??
            "Registry metadata is unavailable; route metadata fallback is active."}
        </p>
      ) : null}

      <div className="module-registry-table-scroll">
        <table className="module-registry-table">
          <thead>
            <tr>
              <th>Module</th>
              <th>Product state</th>
              <th>Org visibility</th>
              <th>Permission</th>
              <th>Adapter</th>
              <th>Execution</th>
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
