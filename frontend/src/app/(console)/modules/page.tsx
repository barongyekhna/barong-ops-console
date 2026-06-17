import type { Metadata } from "next";

import { ModuleRegistryProductView } from "@/components/module-registry-product-view";

export const metadata: Metadata = {
  title: "Modules",
};

export default function ModulesPage() {
  return <ModuleRegistryProductView />;
}
