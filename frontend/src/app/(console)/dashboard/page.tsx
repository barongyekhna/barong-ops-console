import type { Metadata } from "next";

import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default function DashboardPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">OPS</span>
        <div>
          <h2>System Operations Control Center</h2>
          <p>Capability, readiness, observability, approval, and health status.</p>
        </div>
      </div>
      <OperationsDashboard />
    </div>
  );
}
