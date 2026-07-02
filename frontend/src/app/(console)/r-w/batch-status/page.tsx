import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W 批次状态",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwBatchStatusPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-W</span>
        <div>
          <h1>R-W 产品数据仓库</h1>
          <p>Keepa 队列和 DeepSeek 自动批处理状态。</p>
        </div>
      </section>

      <WarehouseWorkspace view="batch" />
    </div>
  );
}
