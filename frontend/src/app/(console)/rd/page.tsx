import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { RemoteDesktopDashboard } from "@/modules/rd/RemoteDesktopDashboard";

export const metadata: Metadata = {
  title: "远程桌面",
};

export default function RemoteDesktopPage() {
  return (
    <DashboardAccessControl>
      <RemoteDesktopDashboard />
    </DashboardAccessControl>
  );
}
