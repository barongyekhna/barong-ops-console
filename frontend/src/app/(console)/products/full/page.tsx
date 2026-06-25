import type { Metadata } from "next";

import { ProductListFull } from "@/modules/k/product-knowledge/ProductList";

export const metadata: Metadata = {
  title: "完整产品列表",
};

export default function FullProductsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">K</span>
        <h1>完整产品列表</h1>
        <p>
          Manage product records, variants, generated outputs, media bindings,
          and safe deletion.
        </p>
      </section>

      <ProductListFull />
    </div>
  );
}
