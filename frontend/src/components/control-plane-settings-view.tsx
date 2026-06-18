"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";

function display(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(", ") : "None";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function ControlPlaneSettingsView() {
  const {
    adapterAccessResult,
    adapterRegistryResult,
    executionAccessResult,
    executionRegistryResult,
    isLoading,
    liveGate,
    liveGateErrors,
    liveGateReports,
    refresh,
  } = useFrontendCapabilityState();

  const executionProviders = executionRegistryResult?.data.items ?? [];
  const executionAccess = executionAccessResult?.data.items ?? [];
  const adapters = adapterRegistryResult?.data.items ?? [];
  const adapterAccess = adapterAccessResult?.data.items ?? [];
  const policies = liveGateReports.policies;
  const readinessChecks = liveGateReports.readiness?.checks ?? [];
  const productionChecks = liveGateReports.productionReadiness?.checks ?? [];

  return (
    <section className="product-console" aria-label="Settings">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Control plane</span>
          <h2>Settings</h2>
          <p>
            Execution providers, module adapters, live gate readiness, and policy
            mapping for the current workspace.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void refresh()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Execution mode</span>
          <strong>{liveGate.execution_mode}</strong>
        </div>
        <div>
          <span>Live gate</span>
          <strong>{liveGate.live_gate_status}</strong>
        </div>
        <div>
          <span>Providers</span>
          <strong>{executionProviders.length}</strong>
        </div>
        <div>
          <span>Adapters</span>
          <strong>{adapters.length}</strong>
        </div>
        <div>
          <span>Policies</span>
          <strong>{policies.length}</strong>
        </div>
      </div>

      {liveGateErrors.readiness ||
      liveGateErrors.productionReadiness ||
      liveGateErrors.policies ? (
        <p className="ops-warning">
          {liveGateErrors.readiness ??
            liveGateErrors.productionReadiness ??
            liveGateErrors.policies}
        </p>
      ) : null}

      <div className="product-console-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Execution Provider Mapping</h3>
              <p>/execution-providers/registry and /execution-providers/me</p>
            </div>
            <span className="ops-source">{executionAccess.length} access rows</span>
          </div>
          <div className="module-registry-table-scroll product-table-scroll">
            <table className="module-registry-table product-table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Module</th>
                  <th>Adapter</th>
                  <th>Action</th>
                  <th>Status</th>
                  <th>Mode</th>
                </tr>
              </thead>
              <tbody>
                {executionProviders.length > 0 ? (
                  executionProviders.map((provider) => (
                    <tr key={provider.provider_key}>
                      <td>
                        <strong>{provider.provider_key}</strong>
                      </td>
                      <td>
                        <strong>{provider.module_key}</strong>
                      </td>
                      <td>
                        <strong>{provider.adapter_key}</strong>
                      </td>
                      <td>
                        <strong>{provider.action_key}</strong>
                      </td>
                      <td>
                        <strong>{provider.provider_status}</strong>
                      </td>
                      <td>
                        <strong>{display(provider.supported_execution_modes)}</strong>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6}>
                      <strong>No execution providers declared.</strong>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Module Adapter Mapping</h3>
              <p>/module-adapters/registry and /module-adapters/me</p>
            </div>
            <span className="ops-source">{adapterAccess.length} access rows</span>
          </div>
          <div className="module-registry-table-scroll product-table-scroll">
            <table className="module-registry-table product-table">
              <thead>
                <tr>
                  <th>Adapter</th>
                  <th>Module</th>
                  <th>Status</th>
                  <th>Surfaces</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {adapters.length > 0 ? (
                  adapters.map((adapter) => (
                    <tr key={adapter.adapter_key}>
                      <td>
                        <strong>{adapter.adapter_key}</strong>
                      </td>
                      <td>
                        <strong>{adapter.module_key}</strong>
                      </td>
                      <td>
                        <strong>{adapter.adapter_status}</strong>
                      </td>
                      <td>
                        <strong>{display(adapter.supported_surfaces)}</strong>
                      </td>
                      <td>
                        <strong>
                          {display(
                            adapter.action_contracts.map(
                              (contract) => contract.action_key,
                            ),
                          )}
                        </strong>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5}>
                      <strong>No module adapters declared.</strong>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
      </div>

      <section className="ops-dashboard-grid">
        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Readiness Checks</h3>
              <p>/live-gate/readiness</p>
            </div>
            <span className="ops-source">
              {liveGate.readiness_passed ? "passed" : "review"}
            </span>
          </div>
          {readinessChecks.length > 0 ? (
            <ol className="ops-record-list">
              {readinessChecks.map((check) => (
                <li key={check.check}>
                  <span>{check.status}</span>
                  <strong>{check.check}</strong>
                  <small>{check.reason}</small>
                </li>
              ))}
            </ol>
          ) : (
            <div className="ops-empty-state">
              <strong>No readiness checks returned.</strong>
              <span>/live-gate/readiness</span>
            </div>
          )}
        </article>

        <article className="ops-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>Production Checks</h3>
              <p>/live-gate/production-readiness</p>
            </div>
            <span className="ops-source">
              {liveGate.production_ready ? "ready" : "review"}
            </span>
          </div>
          {productionChecks.length > 0 ? (
            <ol className="ops-record-list">
              {productionChecks.map((check) => (
                <li key={check.check}>
                  <span>{check.status}</span>
                  <strong>{check.check}</strong>
                  <small>{check.reason}</small>
                </li>
              ))}
            </ol>
          ) : (
            <div className="ops-empty-state">
              <strong>No production checks returned.</strong>
              <span>/live-gate/production-readiness</span>
            </div>
          )}
        </article>

        <article className="ops-panel ops-panel-wide">
          <div className="ops-panel-heading">
            <div>
              <h3>Live Policies</h3>
              <p>/live-gate/policies</p>
            </div>
            <span className="ops-source">{policies.length} policies</span>
          </div>
          {policies.length > 0 ? (
            <ol className="ops-record-list">
              {policies.map((policy) => (
                <li key={policy.policy_id}>
                  <span>{policy.status}</span>
                  <strong>{policy.policy_id}</strong>
                  <small>
                    {policy.policy_scope} / {policy.scope_key} / rollout{" "}
                    {policy.rollout_percentage}%
                  </small>
                </li>
              ))}
            </ol>
          ) : (
            <div className="ops-empty-state">
              <strong>No live policies returned.</strong>
              <span>/live-gate/policies</span>
            </div>
          )}
        </article>
      </section>
    </section>
  );
}
