import type { Metadata } from "next";

import { AnalysisWorkspace } from "@/modules/r/analysis/AnalysisWorkspace";

export const metadata: Metadata = {
  title: "R-A 产品深度分析",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RaAnalysisPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">R-A</span>
        <div>
          <h1>R-A 产品分析中心</h1>
          <p>三层 AI、供应商成本、利润测算和最终选品报告的工作台框架。</p>
        </div>
      </section>

      <AnalysisWorkspace view="analysis" />
    </div>
  );
}
