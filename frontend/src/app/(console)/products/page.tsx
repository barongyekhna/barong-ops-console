import type { Metadata } from "next";

import { ProductList } from "@/modules/k/product-knowledge/ProductList";

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

      {K7_CONSOLE_MODE ? <ProductList /> : null}
    </div>
  );
}
