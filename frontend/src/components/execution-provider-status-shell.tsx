"use client";

import { CircleSlash2 } from "lucide-react";

import {
  getExecutionProviderActionState,
  getExecutionProviderStatusLabel,
  type ExecutionProviderAccessState,
  type ExecutionProviderContract,
} from "@/lib/execution-provider";
import type { AdapterActionContract } from "@/lib/module-adapter";

export function ExecutionProviderStatusShell({
  actionContract,
  provider,
  providerAccessState,
}: {
  actionContract: AdapterActionContract;
  provider?: ExecutionProviderContract | null;
  providerAccessState?: ExecutionProviderAccessState | null;
}) {
  const actionState = getExecutionProviderActionState({
    accessState: providerAccessState,
    requiresApproval: actionContract.requires_approval,
    requiresExecutionProvider: actionContract.requires_execution_provider,
  });
  const providerStatus = providerAccessState?.provider_status ?? provider?.provider_status;
  const providerAccess = providerAccessState?.provider_access_state ?? "provider_pending";
  const noExecuteReason =
    providerAccessState?.no_execute_reason ||
    provider?.no_execute_reason ||
    actionState.no_execute_reason;
  const safeStatusMessage =
    providerAccessState?.safe_status_message ||
    provider?.safe_status_message ||
    actionState.detail;

  return (
    <aside className="adapter-unavailable-notice" role="status">
      <CircleSlash2 aria-hidden="true" size={18} />
      <div>
        <strong>{actionState.title}</strong>
        <span>{actionState.message}</span>
        <span>
          {`${getExecutionProviderStatusLabel(providerStatus ?? "provider_pending")} / ${providerAccess}`}
        </span>
        <span>{noExecuteReason}</span>
        <span>{safeStatusMessage}</span>
      </div>
      <button disabled type="button">
        {actionState.button_label}
      </button>
    </aside>
  );
}
