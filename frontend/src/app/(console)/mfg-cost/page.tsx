import type { Metadata } from "next";

import { CostWorkspace } from "@/modules/m/cost/CostWorkspace";

export const metadata: Metadata = {
  title: "出货成本",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function MfgCostPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">M</span>
        <div>
          <h1>出货成本</h1>
        </div>
      </section>
      <CostWorkspace />
    </div>
  );
}
