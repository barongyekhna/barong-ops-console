import type { Metadata } from "next";

import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "Operations Hub",
};

export default function DashboardPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">Hub</span>
        <div>
          <h2>Operations Hub</h2>
          <p>Health, users, organizations, approvals, recent operations, and system status.</p>
        </div>
      </div>
      <OperationsDashboard />
    </div>
  );
}
