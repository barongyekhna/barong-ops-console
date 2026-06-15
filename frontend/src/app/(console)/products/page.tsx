import type { Metadata } from "next";

import { ProductList } from "@/modules/k/product-knowledge/ProductList";
import { ResearchTriggerPanel } from "@/modules/k15/research-trigger/ResearchTriggerPanel";
import { SERPTriggerPanel } from "@/modules/k16/serp-trigger/SERPTriggerPanel";
import { KeywordPanel } from "@/modules/k19/keywords";
import { RiskPanel } from "@/modules/k20/risk";

export const metadata: Metadata = {
  title: "Product Knowledge",
};

const K7_CONSOLE_MODE = true;

export default function ProductsPage() {
  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">K07</span>
        <div>
          <h2>Product Knowledge</h2>
          <p>
            Console MVP for creating and reviewing K-series product knowledge
            records.
          </p>
        </div>
      </div>

      <ResearchTriggerPanel />
      <SERPTriggerPanel />
      <KeywordPanel />
      <RiskPanel />

      {K7_CONSOLE_MODE ? <ProductList /> : null}
    </div>
  );
}
