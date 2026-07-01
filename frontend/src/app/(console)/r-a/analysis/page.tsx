import type { Metadata } from "next";

import { AnalysisPlaceholder } from "@/modules/r/analysis/AnalysisPlaceholder";

export const metadata: Metadata = {
  title: "R-A Analysis",
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
          <p>Analysis execution is locked until Warehouse readiness is complete.</p>
        </div>
      </section>

      <AnalysisPlaceholder view="analysis" />
    </div>
  );
}

