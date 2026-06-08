import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Modules",
};

export default function ModulesPage() {
  return (
    <FoundationList
      emptyDescription="Foundation and demo module records will appear here."
      emptyTitle="No modules registered yet."
      endpoint="/modules"
      fields={[
        { key: "module_key", label: "Module key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      title="Module registry"
    />
  );
}
