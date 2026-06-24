import type { Metadata } from "next";

import { ProductList } from "@/modules/k/product-knowledge/ProductList";
import { ResearchTriggerPanel } from "@/modules/k15/research-trigger/ResearchTriggerPanel";
import { SERPTriggerPanel } from "@/modules/k16/serp-trigger/SERPTriggerPanel";
import { KeywordPanel } from "@/modules/k19/keywords";
import { RiskPanel } from "@/modules/k20/risk";

export const metadata: Metadata = {
  title: "产品知识库",
};

export default function ProductsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">K</span>
        <h1>产品知识库</h1>
        <p>
          Product records, keyword research, SERP enrichment, risk filtering,
          and downstream pipeline handoff.
        </p>
      </section>

      <ProductList />

      <div className="page-grid page-grid-two">
        <ResearchTriggerPanel />
        <SERPTriggerPanel />
      </div>

      <KeywordPanel />
      <RiskPanel />
    </div>
  );
}
