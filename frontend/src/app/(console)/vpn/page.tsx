import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { VpnDashboard } from "@/modules/vpn/VpnDashboard";

export const metadata: Metadata = {
  title: "VPN",
};

export default function VpnPage() {
  return (
    <DashboardAccessControl>
      <VpnDashboard />
    </DashboardAccessControl>
  );
}
