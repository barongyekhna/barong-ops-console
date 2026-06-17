import { Package } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Products",
};

export default function ProductsPage() {
  return (
    <CapabilityEmptyState
      icon={Package}
      reason="The products route has no production product API binding in the current capability graph."
      required_execution_mode="Non-mock execution provider mode for product actions."
      required_module_state="business.products must be installed with a durable backend adapter."
      required_org_state="Active organization context must expose business.products."
      required_permission="products.read"
      state="hidden"
      title="Products capability is not installed"
      unlock_condition="Install a real products module and backend API binding before exposing this route."
    />
  );
}
