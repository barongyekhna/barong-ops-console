import type { Metadata } from "next";

import { AnalysisPlaceholder } from "@/modules/r/analysis/AnalysisPlaceholder";

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
          <p>Analysis remains inactive until R-W exits mock mode.</p>
        </div>
      </section>

      <AnalysisPlaceholder view="dashboard" />
    </div>
  );
}

