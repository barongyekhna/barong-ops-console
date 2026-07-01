import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W 产品数据仓库",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwDashboardPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-W</span>
        <div>
          <h1>R-W 产品数据仓库</h1>
          <p>Warehouse mock mode is active while Keepa keys remain unbound.</p>
        </div>
      </section>

      <WarehouseWorkspace view="dashboard" />
    </div>
  );
}

