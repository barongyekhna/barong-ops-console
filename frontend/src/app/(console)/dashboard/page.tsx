import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "工作台概览",
};

export default function DashboardPage() {
  return (
    <DashboardAccessControl>
      <OperationsDashboard />
    </DashboardAccessControl>
  );
}
