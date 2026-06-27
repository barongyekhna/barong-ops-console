import type { Metadata } from "next";

import { ProductListFull } from "@/modules/k/product-knowledge/ProductList";

export const metadata: Metadata = {
  title: "产品知识库",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ProductsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">K</span>
        <h1>产品知识库</h1>
        <p>
          创建产品后在列表内展开详情，分别完成关键词、图片和卖点审核。
        </p>
      </section>

      <ProductListFull />
    </div>
  );
}
