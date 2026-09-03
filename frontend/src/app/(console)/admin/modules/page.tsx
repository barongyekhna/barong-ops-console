import { redirect } from "next/navigation";

// M7 (QA 2026-08-22): duplicate of /module-control — redirect to the canonical.
export default function AdminModulesPage() {
  redirect("/module-control");
}
