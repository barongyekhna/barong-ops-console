import type { Metadata } from "next";

import { UserManagementPanel } from "@/components/user-management-panel";

export const metadata: Metadata = {
  title: "用户管理",
};

export default function UsersPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">账号</span>
        <div>
          <h2>用户管理</h2>
          <p>
            管理工作台账号、角色、组织归属和密码重置。
          </p>
        </div>
      </div>
      <UserManagementPanel />
    </div>
  );
}
