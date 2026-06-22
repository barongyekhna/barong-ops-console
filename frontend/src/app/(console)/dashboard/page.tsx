import type { Metadata } from "next";

import { DashboardAccessControl } from "@/components/dashboard-access-control";
import { OperationsDashboard } from "@/components/operations-dashboard";

export const metadata: Metadata = {
  title: "工作台概览",
};

export default function DashboardPage() {
  return (
    <DashboardAccessControl>
      <div className="page-stack">
        <div className="page-heading">
          <span className="section-index">首页</span>
          <div>
            <h2>工作台概览</h2>
            <p>
              查看账号、组织、审批和系统状态。
            </p>
          </div>
        </div>
        <OperationsDashboard />
      </div>
    </DashboardAccessControl>
  );
}
