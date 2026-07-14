import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "VPN",
};

export default function VpnPage() {
  return (
    <DashboardAccessControl>
      <OperationsDashboard />
    </DashboardAccessControl>
  );
}
