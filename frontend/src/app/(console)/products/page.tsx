import type { Metadata } from "next";

import { ProductListFull } from "@/modules/k/product-knowledge/ProductList";

export const metadata: Metadata = {
  title: "产品知识库",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function ProductsPage() {
  return <ProductListFull />;
}
