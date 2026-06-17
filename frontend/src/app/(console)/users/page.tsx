import type { Metadata } from "next";

import { UserManagementPanel } from "@/components/user-management-panel";

export const metadata: Metadata = {
  title: "Users",
};

export default function UsersPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">Core</span>
        <div>
          <h2>Users</h2>
          <p>
            Manage workspace accounts, roles, passwords, and access from one place.
          </p>
        </div>
      </div>
      <UserManagementPanel />
    </div>
  );
}
