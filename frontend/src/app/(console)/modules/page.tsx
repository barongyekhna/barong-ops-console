import { redirect } from "next/navigation";

// M7 (QA 2026-08-22): /modules, /admin/modules and /module-control rendered the
// identical ModuleRegistryProductView. Consolidated on /module-control; this
// route redirects so old links keep working without a duplicate page.
export default function ModulesPage() {
  redirect("/module-control");
}
