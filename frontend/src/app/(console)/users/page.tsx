import type { Metadata } from "next";

import { UserManagementPanel } from "@/components/user-management-panel";

export const metadata: Metadata = {
  title: "User Management",
};

export default function UsersPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">C03</span>
        <div>
          <h2>User Management</h2>
          <p>
            Internal account management for owner-created console users. This
            page is not a public registration flow.
          </p>
        </div>
      </div>
      <UserManagementPanel />
    </div>
  );
}
