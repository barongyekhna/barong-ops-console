import type { Metadata } from "next";

import { ProductListFull } from "@/modules/k/product-knowledge/ProductList";

export const metadata: Metadata = {
  title: "完整产品列表",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function FullProductsPage() {
  return <ProductListFull />;
}
