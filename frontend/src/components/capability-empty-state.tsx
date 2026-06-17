import {
  Building2,
  CircleSlash2,
  Inbox,
  LockKeyhole,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

export type CapabilityEmptyStateName =
  | "no_data"
  | "no_permission"
  | "no_organization"
  | "missing_feature"
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
  next_action_href?: string;
  next_action_label?: string;
};

type ProductEmptyStateName =
  | "no_data"
  | "no_permission"
  | "no_organization"
  | "missing_feature";

const STATE_ICON: Record<ProductEmptyStateName, LucideIcon> = {
  missing_feature: CircleSlash2,
  no_data: Inbox,
  no_organization: Building2,
  no_permission: LockKeyhole,
};

const STATE_LABEL: Record<ProductEmptyStateName, string> = {
  missing_feature: "Missing feature",
  no_data: "No data",
  no_organization: "No organization",
  no_permission: "No permission",
};

const DEFAULT_NEXT_ACTION: Record<
  ProductEmptyStateName,
  { href: string; label: string }
> = {
  missing_feature: {
    href: "/dashboard",
    label: "Open dashboard",
  },
  no_data: {
    href: "",
    label: "Refresh",
  },
  no_organization: {
    href: "/organizations",
    label: "Open organizations",
  },
  no_permission: {
    href: "/users",
    label: "Open users",
  },
};

function productStateFor(state: CapabilityEmptyStateName): ProductEmptyStateName {
  if (
    state === "forbidden" ||
    state === "hidden" ||
    state === "no_permission"
  ) {
    return "no_permission";
  }
  if (state === "no_organization") {
    return "no_organization";
  }
  if (state === "allowed" || state === "no_data") {
    return "no_data";
  }
  return "missing_feature";
}

function iconForState(state: ProductEmptyStateName) {
  if (state === "no_permission") {
    return ShieldAlert;
  }
  return STATE_ICON[state];
}

function reasonForState({
  productState,
  reason,
}: {
  productState: ProductEmptyStateName;
  reason: string;
}) {
  const trimmed = reason.trim();
  if (trimmed) {
    return trimmed;
  }

  if (productState === "no_data") {
    return "There are no records to show yet.";
  }
  if (productState === "no_permission") {
    return "Your account does not have access to this area.";
  }
  if (productState === "no_organization") {
    return "Choose or create an organization before using this area.";
  }
  return "This product area is not available yet.";
}

function NextAction({
  href,
  label,
}: {
  href: string;
  label: string;
}) {
  if (!href) {
    return (
      <a
        className="primary-button"
        href=""
        role="button"
      >
        {label}
      </a>
    );
  }

  return (
    <a className="primary-button" href={href} role="button">
      {label}
    </a>
  );
}

const LEGACY_STATE_CLASS: Record<CapabilityEmptyStateName, string> = {
  adapter_pending: "missing_feature",
  allowed: "no_data",
  backend_unavailable: "missing_feature",
  forbidden: "no_permission",
  hidden: "no_permission",
  missing_feature: "missing_feature",
  mock: "missing_feature",
  no_data: "no_data",
  no_execution: "missing_feature",
  no_organization: "no_organization",
  no_permission: "no_permission",
  partial: "missing_feature",
};

export function CapabilityEmptyStateEngine({
  action,
  icon,
  reason,
  state,
  title,
  next_action_href,
  next_action_label,
}: CapabilityEmptyStateProps) {
  const productState = productStateFor(state);
  const Icon = icon ?? iconForState(productState);
  const nextAction = DEFAULT_NEXT_ACTION[productState];

  return (
    <section
      className={`capability-empty-state capability-empty-state-${LEGACY_STATE_CLASS[state]}`}
      role={productState === "no_data" ? "status" : "alert"}
    >
      <span className="capability-empty-state-icon">
        <Icon aria-hidden="true" size={24} />
      </span>
      <div className="capability-empty-state-copy">
        <span className="capability-state-badge">
          {STATE_LABEL[productState]}
        </span>
        <h2>{title}</h2>
        <p>{reasonForState({ productState, reason })}</p>
        <div className="capability-empty-action">
          {action ?? (
            <NextAction
              href={next_action_href ?? nextAction.href}
              label={next_action_label ?? nextAction.label}
            />
          )}
        </div>
      </div>
    </section>
  );
}

export const CapabilityEmptyState = CapabilityEmptyStateEngine;
