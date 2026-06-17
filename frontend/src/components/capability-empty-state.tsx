import {
  CircleSlash2,
  LockKeyhole,
  PlugZap,
  ShieldAlert,
  Split,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

export type CapabilityEmptyStateName =
  | "allowed"
  | "forbidden"
  | "hidden"
  | "partial"
  | "mock"
  | "adapter_pending"
  | "no_execution"
  | "backend_unavailable";

export type CapabilityEmptyStateProps = {
  state: CapabilityEmptyStateName;
  title: string;
  reason: string;
  unlock_condition: string;
  required_permission: string;
  required_org_state: string;
  required_module_state: string;
  required_execution_mode: string;
  icon?: LucideIcon;
  action?: ReactNode;
};

const STATE_ICON: Record<CapabilityEmptyStateName, LucideIcon> = {
  adapter_pending: PlugZap,
  allowed: Split,
  backend_unavailable: CircleSlash2,
  forbidden: LockKeyhole,
  hidden: ShieldAlert,
  mock: PlugZap,
  no_execution: CircleSlash2,
  partial: Split,
};

const STATE_LABEL: Record<CapabilityEmptyStateName, string> = {
  adapter_pending: "Adapter pending",
  allowed: "Allowed",
  backend_unavailable: "Backend unavailable",
  forbidden: "Forbidden",
  hidden: "Hidden",
  mock: "Mock",
  no_execution: "No execution",
  partial: "Partial",
};

export function CapabilityEmptyState({
  action,
  icon,
  reason,
  required_execution_mode,
  required_module_state,
  required_org_state,
  required_permission,
  state,
  title,
  unlock_condition,
}: CapabilityEmptyStateProps) {
  const Icon = icon ?? STATE_ICON[state];

  return (
    <section
      className={`capability-empty-state capability-empty-state-${state}`}
      role={state === "allowed" ? "status" : "alert"}
    >
      <span className="capability-empty-state-icon">
        <Icon aria-hidden="true" size={24} />
      </span>
      <div className="capability-empty-state-copy">
        <span className="capability-state-badge">{STATE_LABEL[state]}</span>
        <h2>{title}</h2>
        <p>{reason}</p>
        <dl className="capability-requirements">
          <div>
            <dt>Unlock condition</dt>
            <dd>{unlock_condition}</dd>
          </div>
          <div>
            <dt>Required permission</dt>
            <dd>{required_permission}</dd>
          </div>
          <div>
            <dt>Required org state</dt>
            <dd>{required_org_state}</dd>
          </div>
          <div>
            <dt>Required module state</dt>
            <dd>{required_module_state}</dd>
          </div>
          <div>
            <dt>Required execution mode</dt>
            <dd>{required_execution_mode}</dd>
          </div>
        </dl>
        {action ? <div className="capability-empty-action">{action}</div> : null}
      </div>
    </section>
  );
}
