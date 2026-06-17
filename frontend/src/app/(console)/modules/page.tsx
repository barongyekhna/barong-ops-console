import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Modules",
};

export default function ModulesPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No module records match the current backend result set."
      emptyTitle="No modules registered yet."
      endpoint="/modules"
      fields={[
        { key: "module_key", label: "Module key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="modules.read"
      title="Module registry"
    />
  );
}
