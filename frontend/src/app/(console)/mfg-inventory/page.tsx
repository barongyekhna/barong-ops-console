import type { Metadata } from "next";

import { InventoryWorkspace } from "@/modules/m/inventory/InventoryWorkspace";

export const metadata: Metadata = {
  title: "库存",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function MfgInventoryPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">M</span>
        <div>
          <h1>库存</h1>
        </div>
      </section>
      <InventoryWorkspace />
    </div>
  );
}
