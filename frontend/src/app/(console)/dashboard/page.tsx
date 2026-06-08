import { Activity } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Dashboard",
};

export default function DashboardPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">01</span>
        <div>
          <h2>Dashboard</h2>
          <p>Operational activity across the console.</p>
        </div>
      </div>
      <EmptyState
        description="Foundation APIs have not recorded any operational activity."
        icon={Activity}
        title="No operational activity yet."
      />
    </div>
  );
}
