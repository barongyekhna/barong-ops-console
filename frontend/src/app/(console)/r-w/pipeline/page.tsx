import type { Metadata } from "next";

import { WarehouseWorkspace } from "@/modules/r/warehouse/WarehouseWorkspace";

export const metadata: Metadata = {
  title: "R-W 抓取流水线",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RwPipelinePage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-W</span>
        <div>
          <h1>R-W 产品数据仓库</h1>
          <p>Keepa、类目调度、DeepSeek 初筛和写库事件。</p>
        </div>
      </section>

      <WarehouseWorkspace view="pipeline" />
    </div>
  );
}
