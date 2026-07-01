import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W Products",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwProductsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-W</span>
        <div>
          <h1>R-W 产品数据仓库</h1>
          <p>Normalized product rows from the mock Keepa enrichment pipeline.</p>
        </div>
      </section>

      <WarehouseWorkspace view="products" />
    </div>
  );
}

