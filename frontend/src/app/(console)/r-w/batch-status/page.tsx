import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W 批次状态",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwBatchStatusPage() {
  return <WarehouseWorkspace view="batch" />;
}
