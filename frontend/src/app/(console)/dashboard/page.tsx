import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "Operations Hub",
};

export default function DashboardPage() {
  return (
    <DashboardAccessControl>
      <div className="page-stack">
        <div className="page-heading">
          <span className="section-index">Hub</span>
          <div>
            <h2>Operations Hub</h2>
            <p>
              System Health Card, Users Overview, Organizations Overview,
              Approvals Queue, Logs, and Execution Status.
            </p>
          </div>
        </div>
        <OperationsDashboard />
      </div>
    </DashboardAccessControl>
  );
}
