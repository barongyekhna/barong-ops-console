import type { Metadata } from "next";

import { AnalysisWorkspace } from "@/modules/r/analysis/AnalysisWorkspace";

export const metadata: Metadata = {
  title: "R-A 产品分析中心",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RaDashboardPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-A</span>
        <div>
          <h1>R-A 产品分析中心</h1>
          <p>从 R-W 产品仓库进入深度分析、供货商成本和最终选品决策。</p>
        </div>
      </section>

      <AnalysisWorkspace view="dashboard" />
    </div>
  );
}
