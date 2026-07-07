import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W 规则",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwRulesPage() {
  return <WarehouseWorkspace view="rules" />;
}
